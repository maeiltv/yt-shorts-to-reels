#!/usr/bin/env python3
"""
YouTube Shorts -> Instagram Reels 자동 재게시 스크립트.

동작 개요
1. 유튜브 채널 RSS 피드에서 최신 영상 목록을 읽는다.
2. yt-dlp 로 각 영상의 메타데이터를 확인해 '쇼츠'(세로형 + 3분 이하)만 골라낸다.
3. 아직 올리지 않은 새 쇼츠를 다운로드한다.
4. 다운로드한 mp4 를 GitHub Release 에셋으로 업로드해 '공개 URL'을 얻는다.
   (인스타그램 그래프 API 는 공개적으로 접근 가능한 video_url 을 요구한다.)
5. 인스타그램 그래프 API 로 릴스 컨테이너 생성 -> 처리 완료 대기 -> 발행.
6. 처리한 영상 ID 를 posted.json 에 기록한다 (중복 게시 방지).

인증 방식: Instagram API with Instagram Login (graph.instagram.com)
- 페이스북 페이지가 필요 없고, 인스타 프로페셔널 계정으로 직접 로그인해 토큰을 발급.

환경변수 (GitHub Secrets 로 주입)
- IG_USER_ID       : 인스타그램 비즈니스 계정 ID (예: 17841426624408564)
- IG_ACCESS_TOKEN  : Instagram 로그인으로 발급한 장기(60일) 액세스 토큰
- YT_CHANNEL_ID    : 유튜브 채널 ID (UC... 로 시작)
- GITHUB_TOKEN     : Actions 가 자동 제공 (Release 업로드용)
- GITHUB_REPOSITORY: Actions 가 자동 제공 (owner/repo)

환경변수 (선택, 워크플로 env 로 조정)
- MAX_PER_RUN      : 한 번 실행에 최대 몇 개까지 올릴지 (기본 1)
- SHORT_MAX_SECONDS: 쇼츠로 인정할 최대 길이 초 (기본 185)
- CAPTION_TEMPLATE : 캡션 템플릿. {title} 치환. 기본은 제목 그대로.
- DRY_RUN          : "1" 이면 인스타 발행 없이 로그만 (테스트용)
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET

# Instagram 로그인(Instagram API with Instagram Login) 방식 -> graph.instagram.com 사용
GRAPH = "https://graph.instagram.com"
STATE_FILE = "posted.json"

# ---------------------------------------------------------------------------
# 설정 읽기
# ---------------------------------------------------------------------------
IG_USER_ID = os.environ.get("IG_USER_ID", "").strip()
IG_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
YT_CHANNEL_ID = os.environ.get("YT_CHANNEL_ID", "").strip()
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GH_REPO = os.environ.get("GITHUB_REPOSITORY", "").strip()  # owner/repo

MAX_PER_RUN = int(os.environ.get("MAX_PER_RUN", "1"))
SHORT_MAX_SECONDS = int(os.environ.get("SHORT_MAX_SECONDS", "185"))
CAPTION_TEMPLATE = os.environ.get("CAPTION_TEMPLATE", "{title}")
DRY_RUN = os.environ.get("DRY_RUN", "").strip() == "1"

RSS_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={YT_CHANNEL_ID}"


def log(msg):
    print(msg, flush=True)


def die(msg, code=1):
    log(f"::error::{msg}")
    sys.exit(code)


# ---------------------------------------------------------------------------
# 상태 파일 (이미 올린 영상 ID 목록)
# ---------------------------------------------------------------------------
def load_state():
    if not os.path.exists(STATE_FILE):
        return {"posted": [], "seeded": False}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("posted", [])
        data.setdefault("seeded", False)
        return data
    except Exception as e:
        log(f"상태 파일 읽기 실패, 새로 시작합니다: {e}")
        return {"posted": [], "seeded": False}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 1) RSS 피드에서 최신 영상 목록 읽기
# ---------------------------------------------------------------------------
def fetch_feed_videos():
    req = urllib.request.Request(RSS_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
    }
    root = ET.fromstring(raw)
    videos = []
    for entry in root.findall("atom:entry", ns):
        vid = entry.find("yt:videoId", ns)
        title = entry.find("atom:title", ns)
        published = entry.find("atom:published", ns)
        if vid is None or title is None:
            continue
        videos.append({
            "id": vid.text.strip(),
            "title": title.text.strip() if title.text else "",
            "published": published.text if published is not None else "",
        })
    return videos


# ---------------------------------------------------------------------------
# 2) yt-dlp 로 쇼츠 판별
# ---------------------------------------------------------------------------
def get_video_info(video_id):
    """yt-dlp --dump-json 으로 메타데이터 추출. 실패 시 None."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        out = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-warnings", url],
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        log(f"[{video_id}] 메타데이터 조회 타임아웃")
        return None
    if out.returncode != 0:
        log(f"[{video_id}] 메타데이터 조회 실패: {out.stderr.strip()[:200]}")
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


def is_short(info):
    """세로형이고 SHORT_MAX_SECONDS 이하이면 쇼츠로 간주."""
    if not info:
        return False
    duration = info.get("duration") or 0
    width = info.get("width") or 0
    height = info.get("height") or 0
    if duration and duration > SHORT_MAX_SECONDS:
        return False
    if width and height and height <= width:
        return False  # 가로형/정사각형은 제외
    return True


def download_video(video_id, workdir):
    """쇼츠 mp4 다운로드. 성공 시 파일 경로, 실패 시 None."""
    url = f"https://www.youtube.com/shorts/{video_id}"
    out_tmpl = os.path.join(workdir, f"{video_id}.%(ext)s")
    cmd = [
        "yt-dlp",
        "-f", "bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]/b[ext=mp4]/b",
        "--merge-output-format", "mp4",
        "--no-warnings",
        "-o", out_tmpl,
        url,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        log(f"[{video_id}] 다운로드 실패: {r.stderr.strip()[:300]}")
        return None
    path = os.path.join(workdir, f"{video_id}.mp4")
    if not os.path.exists(path):
        # 확장자가 다를 수 있으니 탐색
        for fn in os.listdir(workdir):
            if fn.startswith(video_id + "."):
                return os.path.join(workdir, fn)
        return None
    return path


# ---------------------------------------------------------------------------
# 3) mp4 를 GitHub Release 에셋으로 올려 공개 URL 얻기
# ---------------------------------------------------------------------------
def gh_api(method, url, data=None, headers=None, raw_body=None):
    h = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if headers:
        h.update(headers)
    body = raw_body if raw_body is not None else (
        json.dumps(data).encode() if data is not None else None
    )
    req = urllib.request.Request(url, data=body, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode())


def ensure_release():
    """'media' 태그 릴리스를 확보(없으면 생성)하고 release 객체 반환."""
    tag = "media"
    try:
        return gh_api("GET", f"https://api.github.com/repos/{GH_REPO}/releases/tags/{tag}")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    return gh_api("POST", f"https://api.github.com/repos/{GH_REPO}/releases", data={
        "tag_name": tag,
        "name": "media (auto-uploaded reels source)",
        "body": "인스타 발행용 임시 영상 저장소입니다. 자동 생성됨.",
        "prerelease": True,
    })


def upload_asset(release, file_path, video_id):
    upload_url = release["upload_url"].split("{")[0]
    name = f"{video_id}.mp4"
    # 같은 이름 에셋이 이미 있으면 삭제
    for asset in release.get("assets", []):
        if asset.get("name") == name:
            try:
                gh_api("DELETE", f"https://api.github.com/repos/{GH_REPO}/releases/assets/{asset['id']}")
            except Exception:
                pass
    with open(file_path, "rb") as f:
        blob = f.read()
    asset = gh_api(
        "POST",
        f"{upload_url}?name={name}",
        headers={"Content-Type": "video/mp4"},
        raw_body=blob,
    )
    return asset["browser_download_url"], asset["id"]


def delete_asset(asset_id):
    try:
        gh_api("DELETE", f"https://api.github.com/repos/{GH_REPO}/releases/assets/{asset_id}")
    except Exception as e:
        log(f"에셋 삭제 실패(무시): {e}")


# ---------------------------------------------------------------------------
# 4) 인스타그램 그래프 API 로 릴스 발행
# ---------------------------------------------------------------------------
def graph_post(path, params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"{GRAPH}/{path}", data=data, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def graph_get(path, params):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{GRAPH}/{path}?{q}", method="GET")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def verify_token():
    """토큰이 유효한지 graph.instagram.com/me 로 확인. 계정 username 반환."""
    try:
        me = graph_get("me", {
            "fields": "user_id,username",
            "access_token": IG_TOKEN,
        })
        return me.get("username")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="ignore")[:300]
        die(f"액세스 토큰이 유효하지 않습니다(만료됐을 수 있음). 응답: {detail}")


def publish_reel(video_url, caption):
    # 1) 컨테이너 생성
    container = graph_post(f"{IG_USER_ID}/media", {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "access_token": IG_TOKEN,
    })
    creation_id = container["id"]
    log(f"  컨테이너 생성됨: {creation_id}")

    # 2) 처리 완료 대기 (최대 약 5분)
    for attempt in range(30):
        time.sleep(10)
        st = graph_get(creation_id, {
            "fields": "status_code",
            "access_token": IG_TOKEN,
        })
        code = st.get("status_code")
        log(f"  처리 상태: {code}")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError(f"인스타 처리 오류: {st}")
    else:
        raise RuntimeError("인스타 영상 처리 대기 타임아웃")

    # 3) 발행
    published = graph_post(f"{IG_USER_ID}/media_publish", {
        "creation_id": creation_id,
        "access_token": IG_TOKEN,
    })
    return published.get("id")


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def main():
    missing = [k for k, v in {
        "IG_USER_ID": IG_USER_ID,
        "IG_ACCESS_TOKEN": IG_TOKEN,
        "YT_CHANNEL_ID": YT_CHANNEL_ID,
    }.items() if not v]
    if missing and not DRY_RUN:
        die(f"필수 환경변수 누락: {', '.join(missing)}")

    if not DRY_RUN:
        username = verify_token()
        log(f"인스타 토큰 확인 완료: @{username}")

    state = load_state()
    posted = set(state["posted"])

    log(f"RSS 피드 조회: {RSS_URL}")
    videos = fetch_feed_videos()
    log(f"피드에서 {len(videos)}개 영상 발견")

    # 최초 실행 시드: 기존 영상은 '이미 처리됨'으로 표시하고 아무것도 올리지 않는다.
    # (과거 쇼츠 전체가 한꺼번에 인스타로 쏟아지는 것을 방지)
    if not state["seeded"]:
        for v in videos:
            posted.add(v["id"])
        state["posted"] = sorted(posted)
        state["seeded"] = True
        save_state(state)
        log("최초 실행: 현재 영상들을 기준선으로 저장했습니다. "
            "다음 실행부터 '새 쇼츠'만 올립니다.")
        return

    # 새 영상만, 오래된 것부터 처리 (피드는 최신순)
    new_videos = [v for v in reversed(videos) if v["id"] not in posted]
    log(f"미처리 영상 {len(new_videos)}개")

    uploaded = 0
    workdir = os.path.abspath("work")
    os.makedirs(workdir, exist_ok=True)

    for v in new_videos:
        if uploaded >= MAX_PER_RUN:
            log(f"이번 실행 최대치({MAX_PER_RUN}) 도달, 나머지는 다음 실행에서.")
            break

        vid = v["id"]
        log(f"\n=== [{vid}] {v['title']} ===")
        info = get_video_info(vid)
        if not is_short(info):
            log(f"  쇼츠 아님(가로형이거나 {SHORT_MAX_SECONDS}s 초과) → 건너뜀")
            posted.add(vid)  # 다시 검사하지 않도록 기록
            state["posted"] = sorted(posted)
            save_state(state)
            continue

        caption = CAPTION_TEMPLATE.format(title=v["title"])

        if DRY_RUN:
            log(f"  [DRY_RUN] 여기서 발행 예정. caption={caption!r}")
            posted.add(vid)
            state["posted"] = sorted(posted)
            save_state(state)
            uploaded += 1
            continue

        path = download_video(vid, workdir)
        if not path:
            log("  다운로드 실패 → 다음 실행에서 재시도")
            continue

        size_mb = os.path.getsize(path) / 1024 / 1024
        log(f"  다운로드 완료: {os.path.basename(path)} ({size_mb:.1f} MB)")

        release = ensure_release()
        public_url, asset_id = upload_asset(release, path, vid)
        log(f"  공개 URL 확보: {public_url}")

        try:
            media_id = publish_reel(public_url, caption)
            log(f"  ✅ 인스타 발행 완료: media_id={media_id}")
            posted.add(vid)
            state["posted"] = sorted(posted)
            save_state(state)
            uploaded += 1
        finally:
            delete_asset(asset_id)  # 발행 후 임시 에셋 정리
            try:
                os.remove(path)
            except OSError:
                pass

    log(f"\n완료: 이번 실행에서 {uploaded}개 발행.")


if __name__ == "__main__":
    main()
