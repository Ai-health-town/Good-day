from html.parser import HTMLParser

import pytest

from contacttools import phone_parts,phone_html,matches_contact


@pytest.mark.parametrize("value",["+966 50 000 0001","00966500000001","0500000001","٠٥٠٠٠٠٠٠٠١","\u202b+966 50 000 0001\u202c"])
def test_phone_format_preserves_digit_order_and_normalizes_saudi_formats(value):
    assert phone_parts(value) == ("+966 50 000 0001","+966500000001")


def test_contact_number_is_isolated_and_untrusted_text_cannot_create_links():
    class Phone(HTMLParser):
        def __init__(self): super().__init__(); self.tags=[]; self.text=[]
        def handle_starttag(self,tag,attrs): self.tags.append((tag,dict(attrs)))
        def handle_data(self,data): self.text.append(data)
    result = Phone()
    result.feed(phone_html("+966500000001"))
    assert ("bdi",{"dir":"ltr"}) in result.tags
    assert ("a",{"href":"tel:+966500000001"}) in result.tags
    assert "".join(result.text) == "+966 50 000 0001"
    malicious = Phone()
    malicious.feed(phone_html('<img src=x onerror="alert(1)">'))
    assert not any(tag in ("img","script","a") for tag,_ in malicious.tags)


def test_contact_search_matches_name_email_and_local_or_international_phone():
    contact={"name":"جهة تجريبية","org":"فريق الاختبار","phone":"+966500000001","email":"contact@example.test"}
    for query in ("تجريبية","الاختبار","contact@example.test","0500000001","٠٥٠٠٠٠٠٠٠١","50 000 0001"):
        assert matches_contact(contact,query)
    assert not matches_contact(contact,"جهة مختلفة")


def test_directory_form_stores_phone_canonically_and_card_keeps_it_readable(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from tests.test_ui import healthy,element
    from workspace import Store
    url = "sqlite:///" + str(tmp_path/"contacts.db")
    monkeypatch.setenv("DATABASE_URL",url)
    store=Store(url)
    store.bootstrap("owner","Contacts-test-password-824!")
    token=store.login("owner","Contacts-test-password-824!")
    source='''
import os
import streamlit as st
from components import edit_directory,directory_page
from workspace import Store
from theme import inject
inject()
store=Store(os.environ['DATABASE_URL'])
token=st.session_state['test_token']
state,_=store.read(token)
actor=store.actor(token)
if st.session_state.get('show_card'):
    directory_page(store,token,state,actor,'stakeholders')
else:
    edit_directory(store,token,state,actor,'stakeholders')
'''
    app=AppTest.from_string(source,default_timeout=20)
    app.session_state['test_token']=token
    app.run()
    element(app.text_input,"الاسم").set_value("جهة تجريبية")
    element(app.text_input,"رقم التواصل").set_value("٠٥٠٠٠٠٠٠٠١")
    element(app.button,"حفظ البيانات").click().run()
    healthy(app)
    assert store.read(token)[0]['stakeholders'][0]['phone'] == '+966500000001'
    app.session_state['show_card']=True
    app.run()
    healthy(app)
    assert any('<bdi dir="ltr">' in text.value and '+966 50 000 0001' in text.value for text in app.markdown)
