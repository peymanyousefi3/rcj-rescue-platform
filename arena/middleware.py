from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect
from django.http import HttpResponse
from django.utils.cache import patch_vary_headers
from two_factor.utils import default_device
from .access import staff_otp_required
from .throttle import allow_request
from django.contrib.sessions.middleware import SessionMiddleware


class ReplaySessionMiddleware(SessionMiddleware):
    def process_request(self,request):
        super().process_request(request)
        # This cookie never authenticates the portal or any other application route.
        # Normal authentication, session revocation and OTP checks still run below.
        if request.path.startswith('/replay-view/') and not request.COOKIES.get(settings.SESSION_COOKIE_NAME):
            request.session=self.SessionStore(request.COOKIES.get('asr_replay_session'))

class ProxyAddressMiddleware:
    """Only the explicitly trusted, private ingress may supply the client IP."""
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        from django.utils.crypto import constant_time_compare
        if (settings.TRUST_PROXY_CLIENT_IP and settings.PROXY_SHARED_SECRET and
                constant_time_compare(settings.PROXY_SHARED_SECRET, request.META.get('HTTP_X_ASR_PROXY_TOKEN', ''))):
            from ipaddress import ip_address
            try: address = ip_address(request.META.get('HTTP_X_ASR_CLIENT_IP', ''))
            except ValueError: pass
            else: request.META['REMOTE_ADDR'] = str(address)
        return self.get_response(request)

class UploadBoundaryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        if request.method in ('POST', 'PUT', 'PATCH'):
            try: size = int(request.META.get('CONTENT_LENGTH') or 0)
            except ValueError: size = 0
            limit=65536 if request.path.startswith(('/account','/system/login/')) else settings.UPLOAD_MAX_BATCH_BYTES
            if size > limit:
                return HttpResponse('This upload exceeds the configured batch size. Ask the organizer to adjust the limit.', status=413)
        return self.get_response(request)

class SecurityBoundaryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        protected = request.path.startswith(('/portal/', '/control/', '/system/', '/files/', '/submit/', '/quarantines/', '/notices/', '/recordings/', '/replay-view/', '/fields/', '/field-media/', '/field-viewer/'))
        # Reject anonymous upload bodies before CSRF/form parsing can spool them to disk.
        if request.method=='POST' and request.path.startswith(('/submit/','/quarantines/','/control/','/portal/','/system/')) and not request.user.is_authenticated:
            response=redirect('two_factor:login') if request.path.startswith('/control/') else HttpResponse('Sign in before uploading files.',status=403)
            response['Cache-Control']='private, no-store'
            return response
        if request.method=='POST' and request.path.startswith('/control/') and request.user.is_authenticated and not request.user.is_staff:
            response=redirect('portal');response['Cache-Control']='private, no-store';return response
        if protected and staff_otp_required(request.user) and not request.user.is_verified():
            response=(redirect_to_login(request.get_full_path(),login_url='two_factor:login')
                if default_device(request.user) else redirect('two_factor:setup'))
            response['Cache-Control']='private, no-store'
            return response
        quota=None
        if request.path.startswith('/recordings/'): quota=(300,60,'recordings')
        elif request.path.startswith(('/replay-view/', '/field-media/', '/field-viewer/')): quota=(2400,60,'viewer-assets')
        if request.method=='POST' and request.path=='/accounts/reset/': quota=(10,3600,'password-reset')
        elif request.method=='POST' and request.path in ('/account/login/','/system/login/'): quota=(40,60,'login')
        elif request.method=='POST' and request.path.startswith(('/submit/','/quarantines/')): quota=(30,60,'uploads')
        elif request.method=='POST' and request.path.startswith('/control/'): quota=(120,60,'admin-writes')
        elif request.path.startswith('/files/') and request.method=='GET': quota=(180,60,'downloads')
        if quota:
            accepted,retry=allow_request(request,limit=quota[0],period=quota[1],scope=quota[2])
            if not accepted:
                response=HttpResponse('Too many requests. Please retry shortly.',status=429)
                response['Retry-After']=str(retry)
                response['Cache-Control']='private, no-store'
                return response
        if request.path.startswith('/control/'):
            import secrets
            request.csp_nonce=secrets.token_urlsafe(24)
        response = self.get_response(request)
        style_nonce=" 'nonce-"+request.csp_nonce+"'" if getattr(request,'csp_nonce',None) else ''
        frames = "frame-src 'self'; "
        if not response.has_header('Content-Security-Policy'):
            response['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'"+style_nonce+"; img-src 'self' data:; "
            "font-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'; " + frames
        )
        response['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        if protected or request.path.startswith('/account') or request.user.is_authenticated:
            response['Cache-Control'] = 'private, no-store, max-age=0'
            patch_vary_headers(response, ['Cookie'])
        if request.user.is_authenticated and request.method=='GET' and request.path.startswith(('/portal/','/control/')):
            from .services import audit
            from .access import team_for
            membership=team_for(request.user)
            audit(request.user,'dashboard.viewed',team=membership.team if membership else None,
                detail={'path':request.path,'status':response.status_code})
        return response
