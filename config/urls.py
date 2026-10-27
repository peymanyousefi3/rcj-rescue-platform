from django.contrib import admin
from django.contrib.auth import views as auth
from django.urls import include, path
from two_factor.urls import urlpatterns as tf_urls
from arena.authentication import LoginView
from arena.forms import QueuedPasswordResetForm

urlpatterns = [
    path('account/login/', LoginView.as_view()),
    path('', include(tf_urls)),
    path('accounts/logout/', auth.LogoutView.as_view(), name='logout'),
    path('accounts/password/', auth.PasswordChangeView.as_view(template_name='registration/form.html', success_url='/portal/'), name='password_change'),
    path('accounts/reset/', auth.PasswordResetView.as_view(form_class=QueuedPasswordResetForm, template_name='registration/form.html', email_template_name='registration/reset_email.txt', subject_template_name='registration/reset_subject.txt'), name='password_reset'),
    path('accounts/reset/sent/', auth.PasswordResetDoneView.as_view(template_name='registration/reset_done.html'), name='password_reset_done'),
    path('accounts/reset/<uidb64>/<token>/', auth.PasswordResetConfirmView.as_view(template_name='registration/form.html'), name='password_reset_confirm'),
    path('accounts/reset/complete/', auth.PasswordResetCompleteView.as_view(template_name='registration/reset_complete.html'), name='password_reset_complete'),
    path('system/', admin.site.urls),
    path('', include('arena.urls')),
]
