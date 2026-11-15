// droid-display — keep a screen for the droid's hands when no monitor exists.
//
// Every 5 s it checks the online displays. If there are none (a truly headless
// Mac Studio), it creates a 1920x1080 virtual display with CoreGraphics'
// CGVirtualDisplay (the mechanism remote-desktop and display tools use), so
// screenshots and computer use keep working. When any other display comes
// online it releases its own. It never touches an existing display.
//
// Build: clang -O2 -fobjc-arc droid-display.m -o droid-display -framework Foundation -framework CoreGraphics
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>

@interface CGVirtualDisplayDescriptor : NSObject
@property (retain, nonatomic) dispatch_queue_t queue;
@property (retain, nonatomic) NSString *name;
@property (nonatomic) unsigned int maxPixelsHigh;
@property (nonatomic) unsigned int maxPixelsWide;
@property (nonatomic) CGSize sizeInMillimeters;
@property (nonatomic) unsigned int serialNum;
@property (nonatomic) unsigned int productID;
@property (nonatomic) unsigned int vendorID;
@property (copy, nonatomic) void (^terminationHandler)(id, id);
@end
@interface CGVirtualDisplayMode : NSObject
- (instancetype)initWithWidth:(unsigned int)width height:(unsigned int)height refreshRate:(double)rate;
@end
@interface CGVirtualDisplaySettings : NSObject
@property (retain, nonatomic) NSArray *modes;
@property (nonatomic) unsigned int hiDPI;
@end
@interface CGVirtualDisplay : NSObject
- (instancetype)initWithDescriptor:(CGVirtualDisplayDescriptor *)descriptor;
- (BOOL)applySettings:(CGVirtualDisplaySettings *)settings;
@property (readonly, nonatomic) unsigned int displayID;
@end

static CGVirtualDisplay *mine = nil;

static uint32_t othersOnline(void) {
    CGDirectDisplayID ids[16]; uint32_t n = 0, others = 0;
    if (CGGetOnlineDisplayList(16, ids, &n) != kCGErrorSuccess) return 1;  // unknown: do nothing
    for (uint32_t i = 0; i < n; i++) if (!mine || ids[i] != mine.displayID) others++;
    return others;
}

static void tick(void) {
    uint32_t others = othersOnline();
    if (others == 0 && !mine) {
        Class D = NSClassFromString(@"CGVirtualDisplayDescriptor");
        if (!D) { fprintf(stderr, "CGVirtualDisplay unavailable\n"); return; }
        CGVirtualDisplayDescriptor *d = [[D alloc] init];
        d.queue = dispatch_get_main_queue();
        d.name = @"Jaeger Droid Display";
        d.maxPixelsWide = 1920; d.maxPixelsHigh = 1080;
        d.sizeInMillimeters = CGSizeMake(527, 296);
        d.vendorID = 0x4A47; d.productID = 0x4452; d.serialNum = 1;
        d.terminationHandler = ^(id a, id b) { mine = nil; };
        CGVirtualDisplay *v = [[NSClassFromString(@"CGVirtualDisplay") alloc] initWithDescriptor:d];
        CGVirtualDisplaySettings *s = [[NSClassFromString(@"CGVirtualDisplaySettings") alloc] init];
        s.hiDPI = 0;
        s.modes = @[[[NSClassFromString(@"CGVirtualDisplayMode") alloc] initWithWidth:1920 height:1080 refreshRate:60]];
        if (v && [v applySettings:s]) { mine = v; printf("virtual display %u online\n", v.displayID); fflush(stdout); }
    } else if (others > 0 && mine) {
        printf("display attached; releasing virtual display\n"); fflush(stdout);
        mine = nil;
    }
}

int main(void) {
    @autoreleasepool {
        tick();
        [NSTimer scheduledTimerWithTimeInterval:5 repeats:YES block:^(NSTimer *t) { tick(); }];
        [[NSRunLoop mainRunLoop] run];
    }
    return 0;
}
