from app.pipeline.prefilter import find_emails, find_links, normalize_hash, prefilter


def test_plain_email():
    assert find_emails("Send CV to HR@Acme.ai today") == ["hr@acme.ai"]


def test_multiple_emails_deduped_in_order():
    text = "Mail b@x.com or a@y.in. Again: B@X.com"
    assert find_emails(text) == ["b@x.com", "a@y.in"]


def test_trailing_punctuation_not_part_of_email():
    assert find_emails("Email your resume to: Nadiya@tribecatalyst.in.") == ["nadiya@tribecatalyst.in"]
    assert find_emails("(careers@zeta.ai)") == ["careers@zeta.ai"]


def test_obfuscated_bracket_forms():
    assert find_emails("hr [at] acme [dot] com") == ["hr@acme.com"]
    assert find_emails("jobs(at)zeta(dot)co(dot)in") == ["jobs@zeta.co.in"]
    assert find_emails("hr [at] acme.com") == ["hr@acme.com"]


def test_obfuscated_word_form_needs_word_dot():
    assert find_emails("write to priya at acme dot io") == ["priya@acme.io"]
    # a plain "apply at <website>" is not an email
    assert find_emails("apply at careers.google.com") == []


def test_telegram_handles_are_not_emails():
    assert find_emails("share with us at : @Developer_coder1") == []


def test_hash_ignores_emoji_case_and_spacing():
    a = "🚨 Referral Alert 🚨\n\nCompany - Acme | Role - AI Engineer"
    b = "Referral alert   company - ACME | role - ai engineer!!"
    assert normalize_hash(a) == normalize_hash(b)
    assert normalize_hash(a) != normalize_hash("Company - Beta | Role - AI Engineer")


def test_prefilter_keeps_posts_with_email():
    r = prefilter("Role - AI Engineer. Mail hr@acme.ai")
    assert (r.keep, r.reason, r.emails) == (True, None, ["hr@acme.ai"])
    assert len(r.text_hash) == 64


def test_prefilter_keeps_link_only_posts():
    r = prefilter("Apply here: https://forms.gle/abc123")
    assert (r.keep, r.reason, r.emails, r.links) == (True, None, [], ["https://forms.gle/abc123"])


def test_prefilter_drops_posts_with_no_way_to_apply():
    r = prefilter("How to join the Special Group: share your interview updates with us @Developer_coder1")
    assert (r.keep, r.reason) == (False, "no_apply_method")


def test_find_links_plain_and_bare_short_links():
    text = "Form: https://docs.google.com/forms/d/e/1FAIp/viewform?usp=header. Also lnkd.in/abc (portal)"
    assert find_links(text) == ["https://docs.google.com/forms/d/e/1FAIp/viewform?usp=header", "https://lnkd.in/abc"]


def test_find_links_ignores_telegram_links_and_dedupes():
    text = "Join https://t.me/sde_referrals and t.me/joinchat/x · apply https://binary.so/LSUx8Qf https://binary.so/LSUx8Qf"
    assert find_links(text) == ["https://binary.so/LSUx8Qf"]
