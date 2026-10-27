from django.conf import settings
from two_factor.views import LoginView as TwoFactorLoginView


class LoginView(TwoFactorLoginView):
    def process_step(self, form):
        data = super().process_step(form)
        if self.steps.current == self.AUTH_STEP:
            self.storage.data['remember_browser'] = self.request.POST.get('remember_browser') == 'on'
        return data

    def done(self, form_list, **kwargs):
        remember = self.storage.data.get('remember_browser', False)
        response = super().done(form_list, **kwargs)
        self.request.session.set_expiry(settings.REMEMBER_SESSION_AGE if remember else 0)
        return response
