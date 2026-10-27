import datetime as dt
from django.db.models import F
from django.utils import timezone
from django.utils.crypto import salted_hmac
from .models import RequestQuota

def allow_request(request,*,limit,period):
    now=timezone.now()
    window=int(now.timestamp())//period
    identity=str(request.user.pk) if request.user.is_authenticated else request.META.get('REMOTE_ADDR','unknown')
    key=salted_hmac('arena.requestquota',f'{request.path}:{identity}:{window}',algorithm='sha256').hexdigest()
    expires=dt.datetime.fromtimestamp((window+1)*period,tz=dt.timezone.utc)
    RequestQuota.objects.get_or_create(key=key,defaults={'expires_at':expires})
    accepted=RequestQuota.objects.filter(key=key,count__lt=limit).update(count=F('count')+1)
    return bool(accepted),max(1,int((expires-now).total_seconds()))
