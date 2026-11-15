// droid-ptz — point the droid's head (Insta360 Link / Link 2 gimbal) with
// standard UVC camera-terminal controls: CT_PANTILT_ABSOLUTE (0x0D) and
// CT_ZOOM_ABSOLUTE (0x0B), as documented in Insta360's UVC SDK guide.
//
// The VideoControl interface is used through its IOCFPlugIn handle WITHOUT
// USBInterfaceOpen, so macOS's own UVC driver keeps streaming and no root,
// entitlement or Insta360 app is needed (technique from J.T. Frey's uvc-util).
//
//   droid-ptz info                 JSON: pan/tilt/zoom min, max, step, current
//   droid-ptz abs <pan> <tilt>     absolute pan/tilt (UVC units, arc-seconds)
//   droid-ptz zoom <value>         absolute zoom
//
// Build: clang -O2 -fobjc-arc droid-ptz.m -o droid-ptz -framework IOKit -framework Foundation
#import <Foundation/Foundation.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/IOCFPlugIn.h>
#include <IOKit/usb/IOUSBLib.h>

static const int VENDOR = 0x2E1A;                  // Insta360
static const int PRODUCTS[] = {0x4C01, 0x4C04, 0x4C05, 0x4C06};  // Link, Link 2 family
static const uint8_t CAMERA_TERMINAL = 1, PANTILT = 0x0D, ZOOM = 0x0B;
static int vcInterface = 0;

static IOUSBInterfaceInterface **findVideoControl(void) {
    io_iterator_t iter = 0;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("IOUSBHostInterface"), &iter) != KERN_SUCCESS) return NULL;
    io_service_t svc;
    IOUSBInterfaceInterface **found = NULL;
    while (!found && (svc = IOIteratorNext(iter))) {
        int vid = -1, pid = -1, cls = -1, sub = -1, num = -1;
        const struct { CFStringRef key; int *out; } props[] = {
            {CFSTR("idVendor"), &vid}, {CFSTR("idProduct"), &pid}, {CFSTR("bInterfaceClass"), &cls},
            {CFSTR("bInterfaceSubClass"), &sub}, {CFSTR("bInterfaceNumber"), &num}};
        for (size_t i = 0; i < 5; i++) {
            CFNumberRef n = IORegistryEntryCreateCFProperty(svc, props[i].key, NULL, 0);
            if (n) { CFNumberGetValue(n, kCFNumberIntType, props[i].out); CFRelease(n); }
        }
        BOOL product = NO;
        for (size_t i = 0; i < sizeof(PRODUCTS) / sizeof(*PRODUCTS); i++) product |= (pid == PRODUCTS[i]);
        if (vid == VENDOR && product && cls == 14 && sub == 1) {
            IOCFPlugInInterface **plugin = NULL; SInt32 score = 0;
            if (IOCreatePlugInInterfaceForService(svc, kIOUSBInterfaceUserClientTypeID, kIOCFPlugInInterfaceID, &plugin, &score) == KERN_SUCCESS && plugin) {
                (*plugin)->QueryInterface(plugin, CFUUIDGetUUIDBytes(kIOUSBInterfaceInterfaceID), (LPVOID *)&found);
                (*plugin)->Release(plugin);
                vcInterface = num;
            }
        }
        IOObjectRelease(svc);
    }
    IOObjectRelease(iter);
    return found;
}

static BOOL request(IOUSBInterfaceInterface **i, uint8_t type, uint8_t req, uint8_t sel, void *buf, uint16_t len) {
    IOUSBDevRequest r = {.bmRequestType = type, .bRequest = req, .wValue = (uint16_t)(sel << 8),
                         .wIndex = (uint16_t)((CAMERA_TERMINAL << 8) | vcInterface), .wLength = len, .pData = buf};
    return (*i)->ControlRequest(i, 0, &r) == kIOReturnSuccess;
}

static NSDictionary *pantilt(IOUSBInterfaceInterface **i, uint8_t req) {
    int32_t v[2] = {0, 0};
    if (!request(i, 0xA1, req, PANTILT, v, 8)) return nil;
    return @{@"pan": @((int32_t)OSSwapLittleToHostInt32(v[0])), @"tilt": @((int32_t)OSSwapLittleToHostInt32(v[1]))};
}

static NSNumber *zoom(IOUSBInterfaceInterface **i, uint8_t req) {
    uint16_t v = 0;
    return request(i, 0xA1, req, ZOOM, &v, 2) ? @(OSSwapLittleToHostInt16(v)) : nil;
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        IOUSBInterfaceInterface **i = findVideoControl();
        if (!i) { fputs("{\"error\":\"Insta360 Link camera not found\"}\n", stdout); return 2; }
        NSString *cmd = argc > 1 ? @(argv[1]) : @"info";
        BOOL ok = YES;
        if ([cmd isEqualToString:@"abs"] && argc > 3) {
            int32_t v[2] = {OSSwapHostToLittleInt32((int32_t)atol(argv[2])), OSSwapHostToLittleInt32((int32_t)atol(argv[3]))};
            ok = request(i, 0x21, 0x01, PANTILT, v, 8);
        } else if ([cmd isEqualToString:@"zoom"] && argc > 2) {
            uint16_t v = OSSwapHostToLittleInt16((uint16_t)atoi(argv[2]));
            ok = request(i, 0x21, 0x01, ZOOM, &v, 2);
        }
        NSMutableDictionary *out = [@{@"ok": @(ok)} mutableCopy];
        NSDictionary *keys = @{@"min": @0x82, @"max": @0x83, @"step": @0x84, @"cur": @0x81};
        for (NSString *k in keys) {
            uint8_t req = (uint8_t)[keys[k] intValue];
            NSDictionary *pt = pantilt(i, req);
            if (pt) out[[@"pantilt_" stringByAppendingString:k]] = pt;
            NSNumber *z = zoom(i, req);
            if (z) out[[@"zoom_" stringByAppendingString:k]] = z;
        }
        (*i)->Release(i);
        NSData *json = [NSJSONSerialization dataWithJSONObject:out options:0 error:nil];
        fwrite(json.bytes, 1, json.length, stdout); fputs("\n", stdout);
        return ok ? 0 : 1;
    }
}
