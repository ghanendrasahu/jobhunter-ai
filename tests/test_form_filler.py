"""Tests for automatic form filling (all pages/handles faked)."""

from jobhunter.automation.form_filler import fill_form

PROFILE = {
    "full_name": "Ada Lovelace",
    "email": "ada@example.com",
    "phone": "+91-9999999999",
    "location": "Bengaluru",
    "current_title": "Software Engineer",
    "experience_years": 3,
    "skills": ["python", "sql"],
    "linkedin": "https://linkedin.com/in/ada",
    "cover_letter": "",
}


class _FakeHandle:
    def __init__(self, attrs=None, tag="INPUT", visible=True, checked=False, options=None):
        self._attrs = attrs or {}
        self._tag = tag
        self._visible = visible
        self._checked = checked
        self._options = options or []
        self.filled = None
        self.selected = None
        self.uploaded = None
        self.checked_set = False
        self.page = None

    def evaluate(self, js):
        if "tagName" in js:
            return self._tag
        if "options" in js or "el.options" in js:
            return list(self._options)
        if "name" in js and "id" in js:
            return f"{self._attrs.get('name', '')}|{self._attrs.get('id', '')}|{self._attrs.get('type', '')}"
        return None

    def is_visible(self):
        return self._visible

    def is_checked(self):
        return self._checked

    def check(self, timeout=None):
        self._checked = True
        self.checked_set = True
        return True

    def get_attribute(self, name):
        return self._attrs.get(name)

    def fill(self, value, timeout=None):
        self.filled = value

    def select_option(self, label=None, timeout=None):
        self.selected = label

    def set_input_files(self, path, timeout=None):
        self.uploaded = path


class _FakeFrame:
    def __init__(self, handles):
        self._handles = handles

    def query_selector_all(self, selector):
        return list(self._handles)


class _FakePage:
    def __init__(self, handles):
        self.frames = [_FakeFrame(handles), _FakeFrame([])]  # second frame is empty
        self.url = "https://www.naukri.com/apply/123"


def test_fill_form_fills_known_fields(tmp_path):
    email_handle = _FakeHandle({"placeholder": "Email", "type": "email", "id": "email"})
    phone_handle = _FakeHandle({"placeholder": "Mobile number", "type": "text", "id": "phone"})
    page = _FakePage([email_handle, phone_handle])
    stats = fill_form(page, PROFILE, None)
    assert email_handle.filled == "ada@example.com"
    assert phone_handle.filled == "+91-9999999999"
    assert stats["filled"] >= 2


def test_password_fields_are_never_filled():
    password = _FakeHandle({"name": "password", "type": "password", "id": "pwd"})
    page = _FakePage([password])
    stats = fill_form(page, PROFILE, None)
    assert password.filled is None
    assert stats["skipped"] >= 1


def test_unknown_fields_reported_not_invented():
    unknown = _FakeHandle({"placeholder": "zzz-qx-99", "id": "zzz-qx-99"})
    page = _FakePage([unknown])
    stats = fill_form(page, PROFILE, None)
    assert unknown.filled is None
    assert stats["unknown"] >= 1


def test_qa_memory_answer_fills_unknown_field(monkeypatch):
    from jobhunter.automation import form_filler

    class _QA:
        def answer_for_question(self, question):
            return type("R", (), {"status": "answer", "intent": "notice_period", "answer": "2 months"})()

    monkeypatch.setattr(form_filler, "intent_matches_field", lambda intent, text: True)
    handle = _FakeHandle({"placeholder": "How many days until you can join?", "id": "join-days"})
    page = _FakePage([handle])
    fill_form(page, PROFILE, None, qa=_QA())
    assert handle.filled == "2 months"


def test_qa_memory_ask_user_leaves_field_alone(monkeypatch):
    from jobhunter.automation import form_filler

    class _QA:
        def answer_for_question(self, question):
            return type("R", (), {"status": "ask_user", "intent": "unknown", "answer": ""})()

    monkeypatch.setattr(form_filler, "intent_matches_field", lambda intent, text: True)
    handle = _FakeHandle({"placeholder": "How many days until you can join?", "id": "join-days"})
    page = _FakePage([handle])
    fill_form(page, PROFILE, None, qa=_QA())
    assert handle.filled is None


def test_resume_file_upload(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fake")
    file_handle = _FakeHandle({"type": "file", "id": "resume"})
    page = _FakePage([file_handle])
    stats = fill_form(page, PROFILE, str(resume))
    assert file_handle.uploaded == str(resume)
    assert stats["file_uploaded"] is True


def test_accept_terms_checkbox_is_checked():
    terms = _FakeHandle({"name": "accept_terms", "type": "checkbox"}, checked=False)
    page = _FakePage([terms])
    fill_form(page, PROFILE, None)
    assert terms.checked_set is True


def test_submit_button_not_filled():
    submit = _FakeHandle({"type": "submit", "id": "submit"})
    page = _FakePage([submit])
    fill_form(page, PROFILE, None)
    assert submit.filled is None


def test_select_without_matching_option_is_missing_not_invented():
    select = _FakeHandle(
        {"placeholder": "Years of experience", "id": "exp"},
        tag="SELECT",
        options=["Select", "0-1 years", "1-2 years"],
    )
    page = _FakePage([select])
    stats = fill_form(page, PROFILE, None)
    assert select.selected is None
    assert "experience_years" in stats["missing"]


def test_select_exact_match_is_selected():
    select = _FakeHandle(
        {"placeholder": "Years of experience", "id": "exp"},
        tag="SELECT",
        options=["Select", "3 years", "5+ years"],
    )
    page = _FakePage([select])
    fill_form(page, PROFILE, None)
    assert select.selected == "3 years"


def test_hidden_field_untouched():
    hidden = _FakeHandle({"type": "hidden", "id": "ts"})
    page = _FakePage([hidden])
    fill_form(page, PROFILE, None)
    assert hidden.filled is None
