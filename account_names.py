"""Persistent display labels, independent of profile identifiers."""
def account_name(settings,account):
    key=str(account)
    value=settings.get('account_'+key+'_name','')
    return value.strip() if isinstance(value,str) and value.strip() else 'Аккаунт '+key

def validate_account_name(value):
    value=value.strip()
    if not value or len(value)>40 or any(ord(c)<32 for c in value):
        raise ValueError('Название аккаунта: от 1 до 40 символов, без переносов.')
    return value
