"""Shared native/legacy profile ingress. Browser traffic uses the WebUI proxy."""
import hmac
import json
from http.server import ThreadingHTTPServer
import threading


class BodyReadTimeout(TimeoutError):
    """The client did not finish its body; native dispatch has not started."""


class ProfileHTTPServer(ThreadingHTTPServer):
    """Bound accepted observers before spawning a request thread."""
    def __init__(self, *args, max_connections=64, **kwargs):
        if not isinstance(max_connections, int) or not 1 <= max_connections <= 1024:
            raise ValueError('max_connections must be in 1..1024')
        self._connections = threading.BoundedSemaphore(max_connections)
        super().__init__(*args, **kwargs)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(15)  # Includes idle keepalive and incomplete headers.
        return request, address

    def process_request(self, request, address):
        if not self._connections.acquire(blocking=False):
            try:
                request.settimeout(1)
                body = b'{"error":"adapter_capacity","retryable":true}'
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\n'
                    b'Content-Type: application/json\r\nConnection: close\r\n'
                    b'Retry-After: 1\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self._connections.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self._connections.release()


class ProfileIngress:
    def profile_authorized(self):
        if self.headers.get('Origin'):
            self.close_connection = True
            self.native_json(403, {'error': 'Use the authenticated WebUI server proxy'})
            return False
        expected = self.native_key()
        if not expected or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + expected):
            self.close_connection = True
            self.native_json(401, {'error': 'Profile gateway credential required'})
            return False
        return True

    def read_json_body(self):
        if self.headers.get('Transfer-Encoding'):
            raise ValueError('Transfer-Encoding is not supported')
        if len(self.headers.get_all('Content-Length', [])) != 1:
            raise ValueError('Exactly one Content-Length is required')
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            raise ValueError('Content-Type must be application/json')
        length = int(self.headers.get('Content-Length', 0))
        if not 0 < length <= 1_000_000:
            raise ValueError('Invalid request size')
        self.connection.settimeout(15)
        try:
            raw = self.rfile.read(length)
        except TimeoutError:
            raise BodyReadTimeout('Request body timed out before dispatch') from None
        if len(raw) != length:
            raise ValueError('Incomplete request body')
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError('Request must be a JSON object')
        return body

    def legacy_post_authorized(self):
        if not self.profile_authorized():
            return False
        try:
            self._request_body = self.read_json_body()
        except (ValueError, TimeoutError) as exc:
            self.close_connection = True
            self.native_json(408 if isinstance(exc, TimeoutError) else 400, {'error': str(exc)})
            return False
        return True
