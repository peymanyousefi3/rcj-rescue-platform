from django import template
register=template.Library()

@register.filter
def editor_groups(form):
    inline={'email_recipients'} if 'targets' in form.fields else set()
    groups=[('Details',{'location','field','challenge','number','name','title','code','country','school','body','instructions','original_name','category','superteam_challenge','members','subject','message','response','status'}),
        ('Timing',{'first_day','last_day','starts_at','end_mode','duration_minutes','ends_at','opens_at','quarantine_at','deadline'}),
        ('Delivery & access',{'destination','replacement','team','kind','round','quarantine','audience','general','all_teams','public','targets','files','send_email'}),
        ('Account access',{'leader_email','username','active','create_account'}),
        ('Scoring',{'expected_rounds','calculation','discard_count','tie_break','top_count','score_source','zero_score_policy'}),
        ('Publication & status',{'completed','maps_released','playback_url','playback_released','confirmed','phase','workbook_enabled','submissions_enabled'})]
    result=[];placed=set()
    for title,names in groups:
        fields=[field for field in form.visible_fields() if field.name in names and field.name not in inline and not (form.__class__.__name__=='RoundForm' and field.name in {'maps_released','targets','wbt','map_json','info_json','glb','jpeg','field_files'})]
        if fields: result.append({'title':title,'fields':fields});placed.update(f.name for f in fields)
    other=[f for f in form.visible_fields() if f.name not in placed and f.name not in inline and not (form.__class__.__name__=='RoundForm' and f.name in {'maps_released','targets','wbt','map_json','info_json','glb','jpeg','field_files'})]
    if other: result.append({'title':'Settings','fields':other})
    return result
