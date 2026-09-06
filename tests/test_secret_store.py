from secret_store import add_key, get_keys

def test_multiple_keys_are_persisted(tmp_path, monkeypatch):
    import secret_store
    monkeypatch.setattr(secret_store, '_STORE', tmp_path / 'secrets.json')
    add_key('OPENAI_API_KEY', 'one')
    add_key('OPENAI_API_KEY', 'two')
    assert get_keys('OPENAI_API_KEY') == ['one', 'two']
