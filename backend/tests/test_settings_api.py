"""Settings API: the profile every email ends with, and resume versions, always only the signed-in user's."""
import base64

from tests.conftest import requires_db
from tests.test_auth_api import PW, api, bearer, secrets  # noqa: F401 (fixtures)
from tests.test_resume_match import AI_RESUME, make_pdf

pytestmark = requires_db

GOOD = {"full_name": "Chetan Mahajan", "phone": "+91 90000 00000", "linkedin_url": "https://linkedin.com/in/chetan",
        "github_url": "https://github.com/ChetanMahajan715", "sender_email": "c@x.com", "education": "B.Tech",
        "home_city": "Pune", "availability": "Immediately"}


async def user(api, email="a@x.com"):
    return bearer((await api.post("/auth/signup", json={"email": email, "password": PW, "device_name": "t"})).json())


async def test_profile_round_trip_keeps_keys_the_app_does_not_edit(api, db):
    from app.accounts.profile import get_profile, set_profile
    from app.db.models import User
    from sqlalchemy import select

    h = await user(api)
    uid = (await db.execute(select(User.id).where(User.email == "a@x.com"))).scalar_one()
    await set_profile(db, uid, {"target_roles": ["AI Engineer"]})
    assert (await api.get("/profile", headers=h)).json()["full_name"] == ""
    assert (await api.put("/profile", headers=h, json=GOOD)).status_code == 200
    assert (await api.get("/profile", headers=h)).json() == GOOD
    db.expire_all()
    assert (await get_profile(db, uid))["target_roles"] == ["AI Engineer"]


async def test_profile_validation_names_each_bad_field(api, db):
    h = await user(api)
    r = await api.put("/profile", headers=h, json={**GOOD, "linkedin_url": "https://github.com/x", "phone": "123"})
    assert r.status_code == 422
    assert {e["loc"][-1] for e in r.json()["detail"]} == {"linkedin_url", "phone"}


def upload(name="AI", text=AI_RESUME):
    return {"name": name, "filename": "cv.pdf", "data": base64.b64encode(make_pdf(text)).decode()}


async def test_upload_list_activate_delete(api, db):
    h = await user(api)
    await api.put("/profile", headers=h, json=GOOD)
    first = (await api.post("/resumes", headers=h, json=upload("Old"))).json()
    second = (await api.post("/resumes", headers=h, json=upload("New"))).json()
    assert second["resume"]["is_active"] and second["outdated_drafts"] == 0 and second["warnings"] == []
    rows = (await api.get("/resumes", headers=h)).json()
    assert [r["name"] for r in rows] == ["New", "Old"] and rows[0]["chars"] > 200 and rows[0]["drafts"] == 0
    old_id = first["resume"]["id"]
    assert (await api.post(f"/resumes/{old_id}/activate", headers=h)).json()["is_active"]
    assert (await api.delete(f"/resumes/{old_id}", headers=h)).status_code == 409
    assert (await api.delete(f"/resumes/{second['resume']['id']}", headers=h)).status_code == 204
    assert [r["name"] for r in (await api.get("/resumes", headers=h)).json()] == ["Old"]


async def test_upload_rejects_non_pdf_and_big_files(api, db):
    h = await user(api)
    bad = {"name": "x", "filename": "cv.docx", "data": base64.b64encode(b"PK..").decode()}
    assert (await api.post("/resumes", headers=h, json=bad)).status_code == 415
    fake = {"name": "x", "filename": "cv.pdf", "data": base64.b64encode(b"hello").decode()}
    assert (await api.post("/resumes", headers=h, json=fake)).status_code == 415
    big = {"name": "x", "filename": "cv.pdf", "data": base64.b64encode(b"%PDF" + b"0" * (5 * 1024 * 1024)).decode()}
    assert (await api.post("/resumes", headers=h, json=big)).status_code in (413, 422)


async def test_other_users_cannot_touch_my_resumes(api, db):
    a = await user(api, "a@x.com")
    b = await user(api, "b@x.com")
    rid = (await api.post("/resumes", headers=a, json=upload())).json()["resume"]["id"]
    assert (await api.get("/resumes", headers=b)).json() == []
    assert (await api.post(f"/resumes/{rid}/activate", headers=b)).status_code == 404
    assert (await api.delete(f"/resumes/{rid}", headers=b)).status_code == 404
