# 유튜브 쇼츠 → 인스타그램 릴스 자동 재게시 (완전 무료)

매일일보TV 유튜브 채널(`UCosM6R_JkU2RlaQR509kpOw`)에 새 **쇼츠**가 올라오면
자동으로 다운로드해서 인스타그램 **릴스**로 발행합니다.
GitHub Actions 의 무료 크론으로 돌기 때문에 서버도, 월 구독료도 필요 없습니다.

작동 방식: RSS로 새 영상 감지 → yt-dlp로 쇼츠만 다운로드 → GitHub Release에
임시 업로드해 공개 URL 확보 → 인스타 그래프 API로 릴스 발행 → 발행한 영상 ID를
`posted.json`에 기록(중복 방지).

---

## 준비물 체크리스트

- [ ] GitHub 계정 (무료)
- [ ] **인스타그램 비즈니스 또는 크리에이터 계정** (개인 계정은 API 발행 불가)
- [ ] 그 인스타 계정과 **연결된 페이스북 페이지**
- [ ] Meta(페이스북) 개발자 계정

> ⚠️ 인스타가 아직 개인 계정이면: 인스타 앱 → 설정 → 계정 유형 전환 → "비즈니스"
> 로 바꾸고, 전환 과정에서 페이스북 페이지를 연결하세요. 이게 가장 중요한 전제조건입니다.

---

## 1단계 — 이 저장소를 내 GitHub에 올리기

1. GitHub에서 새 저장소(repository)를 하나 만듭니다. 이름은 예: `yt-shorts-to-reels`.
   - **Public(공개)로 만드세요.** 인스타가 영상 파일(GitHub Release URL)을 가져가려면
     공개 저장소여야 합니다. (토큰 등 비밀값은 Secrets에 따로 저장되니 노출되지 않습니다.)
2. 이 폴더의 모든 파일(`main.py`, `requirements.txt`, `posted.json`,
   `.github/workflows/repost.yml`, `.gitignore`, `README.md`)을 저장소에 업로드합니다.
   - 웹에서 "Add file → Upload files"로 드래그해서 올려도 됩니다.

---

## 2단계 — 인스타그램 액세스 토큰 만들기 (Instagram 로그인 방식)

> 이 프로젝트는 **"Instagram API with Instagram Login"** 방식을 씁니다.
> 페이스북 페이지 연결이 필요 없고, 인스타 프로페셔널 계정으로 직접 로그인해
> 토큰을 발급받습니다. (아래는 실제로 셋업하며 확인한 절차입니다.)

1. **Meta 개발자 앱**: https://developers.facebook.com/apps 에서 비즈니스 유형 앱 생성
   (이미 `shorts auto` 앱이 만들어져 있습니다).
2. **이용 사례 추가**: 앱 대시보드 → "Instagram에서 메시지 및 콘텐츠 관리" 이용 사례.
3. **권한 추가**: 왼쪽 "권한 및 기능"에서 아래 두 권한을 추가.
   - `instagram_business_basic`
   - `instagram_business_content_publish`
4. **인스타 계정을 테스터로 등록**: 앱 역할 → 역할 → "Instagram 테스터"에 `maeil_star`
   추가 → **인스타에서 초대 수락** (instagram.com → 설정 → 앱 및 웹사이트 →
   "테스터 초대" 탭에서 수락). 앱이 개발 모드일 때 꼭 필요합니다.
5. **토큰 생성**: 이용 사례 → "Instagram 로그인이 포함된 API 설정" → "2. 액세스 토큰 생성"
   → **계정 추가** 로 `maeil_star` 연결 → **토큰 생성** 클릭.
   - 팁: 미리 다른 탭에서 instagram.com 에 `maeil_star` 로 **완전히 로그인**해 두면
     (2FA까지 끝낸 상태), 토큰 생성 팝업이 로그인/2FA를 건너뛰고 바로 "허용"으로 가서
     토큰이 깔끔하게 발급됩니다.
   - 발급된 긴 문자열이 **IG_ACCESS_TOKEN** 입니다.
6. **계정 ID 확인**: 같은 화면의 계정 목록에 뜨는 숫자가 **IG_USER_ID** 입니다.
   (@maeil_star = `17841426624408564`)

> 🔁 **토큰 만료(60일):** 60일마다 같은 자리에서 "토큰 생성"으로 새 토큰을 만들어
> `IG_ACCESS_TOKEN` 시크릿만 교체하면 됩니다.

---

## 3단계 — GitHub Secrets 등록

저장소 → **Settings → Secrets and variables → Actions → New repository secret**
에서 아래 3개를 추가합니다.

| 이름 | 값 |
|------|-----|
| `IG_USER_ID` | `17841426624408564` (인스타 비즈니스 계정 @maeil_star 의 ID) |
| `IG_ACCESS_TOKEN` | 2단계에서 만든 Instagram 로그인 액세스 토큰 |
| `YT_CHANNEL_ID` | `UCosM6R_JkU2RlaQR509kpOw` |

> `GITHUB_TOKEN` 은 Actions가 자동 제공하므로 따로 넣지 않아도 됩니다.
> 토큰은 60일 후 만료되므로, 만료 전 Meta 대시보드에서 다시 "토큰 생성"으로
> 새 토큰을 발급받아 `IG_ACCESS_TOKEN` 시크릿만 교체하면 됩니다.

또한 저장소 → **Settings → Actions → General → Workflow permissions** 에서
**"Read and write permissions"** 를 켜 주세요(상태 파일 `posted.json` 커밋에 필요).

---

## 4단계 — 테스트 실행

1. 저장소 → **Actions** 탭 → 왼쪽 "YouTube Shorts → Instagram Reels" 워크플로 선택.
2. **Run workflow** 클릭.
   - 첫 실행은 **시드(seed)** 실행입니다: 현재 올라와 있는 영상들을 "이미 처리됨"으로만
     기록하고 **아무것도 인스타에 올리지 않습니다.** (과거 영상이 한꺼번에 쏟아지는 걸 방지)
   - 즉, 자동 게시는 이 시드 실행 **이후에 새로 올라오는 쇼츠**부터 시작됩니다.
3. 실제 발행 흐름을 테스트하고 싶으면, `main.py`의 시드 로직을 건너뛰거나
   `posted.json`의 `"seeded": true`로 바꾼 뒤 `Run workflow`에서 `dry_run`을 `0`으로 두고
   실행하면 다음 새 영상부터 바로 발행됩니다. 처음엔 `dry_run`을 `1`로 두고
   로그만 확인하는 것을 권장합니다.

---

## 조정 옵션 (`.github/workflows/repost.yml` 의 `env`)

- `MAX_PER_RUN` — 한 번 실행에 올릴 최대 개수 (기본 1). 너무 크게 올리면 인스타 제한에 걸릴 수 있음.
- `SHORT_MAX_SECONDS` — 쇼츠로 인정할 최대 길이 초 (기본 185).
- `CAPTION_TEMPLATE` — 캡션. 예: `"{title}\n\n#매일일보 #뉴스 #shorts"` 처럼 해시태그 추가 가능.
- 크론 주기 — `cron: "0 */3 * * *"` 는 3시간마다. 하루 한 번이면 `"0 0 * * *"`.
  (시간은 UTC 기준. 한국시간 오전 9시는 UTC 0시입니다.)

---

## 자주 나는 문제

- **`instagram_business_account`가 비어 있음** → 인스타가 비즈니스 계정이 아니거나
  페이스북 페이지에 연결되지 않음. 전제조건 다시 확인.
- **발행이 `ERROR`로 실패** → 영상이 세로형이 아니거나 길이/용량 문제. 인스타 릴스는
  9:16 세로, 3초~15분, 1GB 이하를 권장. 쇼츠는 대부분 조건을 만족합니다.
- **토큰 만료** → 60일마다 `IG_ACCESS_TOKEN` 갱신, 또는 시스템 사용자 토큰 사용.
- **아무것도 안 올라옴** → 아직 "새" 쇼츠가 없을 수 있음. 시드 실행 이후 올라온
  영상부터 대상입니다. Actions 로그에서 "미처리 영상 N개"를 확인하세요.

---

## 무료 사용량 안내

- GitHub Actions: 공개 저장소는 **무제한 무료**, 비공개 저장소도 월 2,000분 무료.
  이 작업은 한 번에 1~3분이라 3시간마다 돌려도 한도에 한참 못 미칩니다.
- 인스타 그래프 API: 무료. 단 콘텐츠 발행은 24시간당 50개 제한(개인 계정 목적엔 충분).
