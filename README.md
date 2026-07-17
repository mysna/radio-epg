# Radio EPG API

`radio.bsod.kr` 라디오 플레이어의 채널 ID와 호환되는 한국 라디오 편성표 API다.
Python Collector가 공식 편성 소스를 수집·검증하고, Cloudflare Worker가 D1에 저장한 채널과
편성을 공개 API로 제공한다.

현재 카탈로그의 194개 정규 채널과 226개 플레이어 별칭은 모두 소유 source가 정해져 있다.
이 중 70개 채널은 fixture로 검증된 adapter가 활성화되어 있고, 124개 채널은 공식 계약을
확인할 때까지 이유와 검증일을 포함한 `unsupported` 상태로 남긴다. 상세 내역은
[`docs/source-coverage.md`](docs/source-coverage.md)에서 확인한다.

## 구성

- `src/radio_epg/`: 수집기, 검증 모델, adapter, 게시 클라이언트
- `data/`: 현재 라디오 채널 카탈로그, source와 채널 매핑
- `worker/`: Hono 기반 Worker와 D1 마이그레이션
- `tests/`: fixture 계약, 통합, 문서와 workflow 테스트
- `.github/workflows/`: CI, 일일 수집, Worker 배포, 비차단 live probe
- `docs/api.md`: 공개·관리 API의 상세 계약

## 로컬 개발

Python 3.12, Node.js 24, `uv`, npm이 필요하다. OCR fixture를 다시 만들거나 live OCR을
실행할 때만 Tesseract와 한국어 데이터, Cairo 런타임이 추가로 필요하다.

```bash
uv sync --locked --dev
npm ci --prefix worker
```

일반 개발은 잠금 파일 그대로 설치하는 `npm ci`를 사용한다. 의존성을 의도적으로
갱신하고 `worker/package-lock.json`도 함께 검토할 때만 `npm install`을 사용한다.

Worker의 로컬 D1을 만들고 실행한다. `worker/.dev.vars.example`을 복사한 뒤 예제 문자열을
로컬 전용 난수로 반드시 바꾼다.

```bash
cd worker
cp .dev.vars.example .dev.vars
npx wrangler d1 migrations apply DB --local
npx wrangler dev
```

다른 터미널에서 같은 토큰을 Collector에 전달한다. 이 프로젝트는 `.env` 파일을 자동으로
읽지 않으므로 셸 환경에 명시적으로 export한다.

```bash
export EPG_API_BASE_URL=http://127.0.0.1:8787
export EPG_INGEST_TOKEN='<LOCAL_RANDOM_TOKEN>'
uv run radio-epg collect --source kbs
```

운영 API에 쓰지 않고 parser만 확인하려면 다음 명령을 사용한다. 별도 `--dry-run`은 없으며,
fixture 검증과 coverage 생성이 네트워크·게시 없는 안전한 dry run 역할을 한다.

```bash
uv run radio-epg validate-fixtures
uv run radio-epg coverage --require-accounted
uv run pytest tests/adapters -q
```

필수 품질 검사는 아래 순서를 유지한다.

```bash
uv run ruff check --fix .
uv run ruff format .
uvx ty check
uv run pytest -q
npm --prefix worker test -- --run
npm --prefix worker run typecheck
git diff --check
```

## Cloudflare 최초 설정

명령은 저장소의 Wrangler 4 잠금 버전을 사용한다. Cloudflare 계정에서 Workers와 D1을
사용할 수 있게 한 뒤 로컬에서는 `cd worker` 상태로 실행한다.

### 1. 로그인과 리소스 생성

```bash
cd worker
npm ci
npx wrangler login
npx wrangler d1 create radio-epg
```

`wrangler d1 create`가 출력한 UUID를 `worker/wrangler.toml`의 `database_id`에 복사한다.

공식 참고 문서: [D1 Wrangler 명령](https://developers.cloudflare.com/d1/wrangler-commands/).

### 2. D1 마이그레이션

로컬과 원격은 별도 데이터베이스다. 먼저 로컬에서 검사하고 원격에 적용한다.

```bash
npx wrangler d1 migrations apply DB --local
npx wrangler d1 migrations apply DB --remote
```

마이그레이션은 순서대로 기록되므로 이미 적용된 파일을 수정하지 않는다. 새 변경은 다음
번호의 SQL 파일로 추가한다. 자세한 동작은
[D1 migrations](https://developers.cloudflare.com/d1/reference/migrations/)를 따른다.

이미지 기능을 사용하던 기존 배포는 `0005_remove_images.sql` 적용과 새 Worker 배포가 끝난
뒤 Cloudflare Dashboard에서 `radio-epg-images` bucket의 기존 객체를 모두 삭제한다. 복구가
필요 없음을 확인한 다음 빈 bucket도 삭제한다. 저장소에서 R2 binding을 먼저 제거했으므로
이 정리는 서비스 요청 경로에 영향을 주지 않으며, 삭제한 객체와 bucket은 복구할 수 없다.

### 3. ingestion secret과 CORS

최소 32바이트 난수를 한 번 생성하고 같은 값을 두 위치에 저장한다.

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
npx wrangler secret put INGEST_TOKEN
```

첫 번째 위치는 Worker secret `INGEST_TOKEN`, 두 번째는 GitHub Actions secret
`EPG_INGEST_TOKEN`이다. 두 값을 README, `.env.example`, `worker/.dev.vars.example`,
`wrangler.toml`에 직접 쓰지 않는다. `wrangler secret put`은 Worker 새 버전을 즉시 만들 수
있으므로 운영 교체 전후에 수집 workflow를 멈추고 두 값을 함께 회전한다.

`CORS_ORIGINS`는 secret이 아니라 쉼표 구분 allowlist다. `worker/wrangler.toml`에서 운영
origin과 필요한 로컬 origin만 정확히 지정한다.

```toml
[vars]
CORS_ORIGINS = "https://radio.bsod.kr,http://localhost:8000"
```

와일드카드는 지원하지 않는다. 서버 간 요청처럼 `Origin`이 없는 요청은 허용되지만,
브라우저 origin은 목록과 정확히 일치해야 한다. Worker secret 사용법은
[Workers secrets](https://developers.cloudflare.com/workers/configuration/secrets/)를 참고한다.

### 4. 최소 권한 배포 토큰

Cloudflare Dashboard의 Account API tokens에서 이 계정 하나만 대상으로 custom token을
만든다. 현재 workflow가 하는 일에 필요한 Account 권한은 다음과 같다.

- `Account Settings Read`
- `Workers Scripts Edit`
- `D1 Edit`

custom domain route를 workflow에서 만들지 않으므로 Zone 전체 권한은 주지 않는다. 이후
route 자동화를 추가할 때만 대상 zone 하나에 `Workers Routes Edit`를 추가한다. 토큰은
`CLOUDFLARE_API_TOKEN`, 계정 ID는 `CLOUDFLARE_ACCOUNT_ID`로 GitHub에 저장한다.
[Cloudflare API token 권한표](https://developers.cloudflare.com/fundamentals/api/reference/permissions/)와
[GitHub Actions 배포 가이드](https://developers.cloudflare.com/workers/ci-cd/external-cicd/github-actions/)에서
현재 명칭을 다시 확인할 수 있다.

### 5. 최초 배포와 smoke 확인

```bash
npx wrangler d1 migrations apply DB --remote
npx wrangler deploy
curl --fail 'https://<WORKER_SUBDOMAIN>.workers.dev/health'
curl --fail 'https://<WORKER_SUBDOMAIN>.workers.dev/v1/channels'
curl --fail 'https://<WORKER_SUBDOMAIN>.workers.dev/v1/coverage'
```

빈 D1에서는 채널 배열이 비어 있는 것이 정상이다. 위 세 endpoint가 응답하면 실제 URL을
GitHub variable `EPG_API_BASE_URL`에 넣고 아래 Actions 설정과 첫 수동 수집을 마친다.
첫 import 이후 Collector의 배포 smoke 명령으로 네 경로(`/health`, `/v1/channels`, 알려진
radio ID, `/v1/coverage`)의 상태와 의미 있는 데이터를 한 번에 검사한다.

```bash
uv run radio-epg smoke \
  --base-url 'https://<WORKER_SUBDOMAIN>.workers.dev' \
  --radio-id 'busan-039-kbs-1radio-busan'
```

## GitHub Actions 설정

Repository **Settings → Secrets and variables → Actions**에서 다음을 만든다.

| 종류 | 이름 | 값 |
| --- | --- | --- |
| Secret | `CLOUDFLARE_API_TOKEN` | 최소 권한 Cloudflare 배포 토큰 |
| Variable | `CLOUDFLARE_ACCOUNT_ID` | 배포 대상 account ID |
| Variable | `EPG_API_BASE_URL` | 배포된 Worker의 HTTPS base URL |
| Secret | `EPG_INGEST_TOKEN` | Worker `INGEST_TOKEN`과 같은 값 |

Repository **Settings → Actions → General**에서 Actions 실행을 허용한다. **Settings →
Environments**에는 이름이 정확히 `production`인 environment를 만들고, 가능하면 required
reviewer와 `main` branch 제한을 설정한다. `deploy-worker.yml`은 이 environment 승인을 받은
뒤 D1 마이그레이션과 Worker 배포를 수행한다.

일일 수집 schedule은 UTC `17 16 * * *`, 즉 다음 날 **01:17 KST**다. GitHub 예약 실행은
부하가 높을 때 지연될 수 있고 default branch에 workflow가 있어야 한다. 즉시 수집하려면
Actions의 **Collect schedules → Run workflow**에서 `workflow_dispatch`를 실행한다. 실패하면
workflow run의 `collection-diagnostics-<RUN_ID>` artifact를 확인하고, 원인을 수정한 뒤
**Re-run failed jobs**를 사용한다. 진단 artifact에는 coverage만 들어가며 환경 변수나 토큰은
덤프하지 않는다. 예약 실행 제약은
[GitHub workflow 이벤트](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows),
보호 규칙은 [deployment environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)를
참고한다.

첫 수동 수집이 성공하면 위 `radio-epg smoke`를 실행한다. 채널 목록이나 coverage가
비었거나 지정한 radio ID 별칭이 보존되지 않으면 smoke는 실패한다.

일일 수집 시도 직후 같은 인증값으로 `POST /v1/admin/retention`을 호출한다. 일부 source가
실패해도 보존 정책은 계속 실행하고, 원래 수집 실패 상태는 workflow에 그대로 남긴다. 이
작업은 KST 오늘과 내일의 편성만 남기고 그보다 과거이거나 먼 미래인 편성 이벤트를
삭제한다. 프로그램, 채널, 별칭은 보존한다.
같은 날짜에 반복 실행해도 결과가 달라지지 않는 멱등 유지보수 작업이다.

`live-probe.yml`은 실제 외부 source 변화를 감시하는 비차단 workflow다. fixture 기반 CI와
분리되어 있으므로 upstream 장애가 코드 병합을 막지 않는다.

## API 예시

정규 채널 ID와 현재 플레이어의 radio ID를 모두 사용할 수 있다.

```bash
API='https://<WORKER_SUBDOMAIN>.workers.dev'
curl --fail "$API/v1/channels/kbs.1radio.busan"
curl --fail "$API/v1/channels/busan-039-kbs-1radio-busan"
curl --fail "$API/v1/schedules?radio_id=busan-039-kbs-1radio-busan&date=2026-07-13"
curl --fail "$API/v1/now?radio_ids=busan-039-kbs-1radio-busan"
curl --fail "$API/v1/coverage"
```

날짜는 KST 방송일 `YYYY-MM-DD`이고 이벤트 시각은 UTC RFC 3339다. `source.stale`이
`true`이면 source별 freshness 기준을 넘긴 결과다. 편성이 없는 채널은 다른 채널의
프로그램을 추측하지 않고 `unavailable`을 반환한다. 전체 계약과 캐시 시간은
[`docs/api.md`](docs/api.md)를 참고한다.

## Source adapter 추가

1. 공식 source URL, channel code, 날짜 범위와 timezone을 먼저 확인한다.
2. 비밀정보를 제거한 최소 원본 응답을 `tests/fixtures/<source>/`에 저장한다.
3. 성공, 빈 응답, schema 변경, 자정 넘김을 먼저 실패하는 테스트로 작성한다.
4. `src/radio_epg/adapters/`에 adapter를 추가하고 strict mapping JSON에 채널을 연결한다.
5. `data/sources.json`에서 fixture 계약이 검증된 뒤에만 `enabled: true`로 바꾼다.
6. 아래 검증으로 모든 카탈로그 채널이 enabled 또는 이유 있는 unsupported인지 확인한다.

```bash
uv run radio-epg validate-fixtures
uv run radio-epg coverage --write docs/source-coverage.md --require-accounted
uv run pytest tests/adapters -q
```

공식 source가 완전히 비어 있는 범위에만 wiki/OCR fallback을 허용한다. fallback 결과에는
낮은 confidence와 `inferred` 성격을 남기며 공식 데이터를 덮지 않는다. 라이브 페이지를
fixture로 자동 갱신하지 말고 구조와 권리를 사람이 검토한다.

## 무료 사용량 모니터링

2026-07-13 기준 공식 무료 구간의 핵심 수치는 Workers 100,000 요청/일, D1 5백만 row
read/일·100,000 row write/일·계정 전체 5GB다. 수치는 바뀔 수 있으므로 운영 전
[Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/),
[D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/)을 다시 확인한다.

Cloudflare Dashboard에서 다음을 주 1회와 장애 발생 시 확인한다.

- Workers 요청 수, CPU time, error rate
- D1 **Metrics → Row Metrics**의 rows read/written과 저장량
- GitHub collection 성공률, source별 stale 수, artifact 생성 여부

유료 계정은 **Manage Account → Billing → Billable Usage → Budget alerts**에서 낮은 임계값의
예산 경고를 만든다. 무료 한도에서도 사용량 화면을 직접 감시한다. D1 인덱스를 제거하거나
전체 scan 쿼리를 추가하기 전에는 rows read 변화를 확인한다. 현재 예산 경고 동작은
[Cloudflare budget alerts](https://developers.cloudflare.com/billing/manage/budget-alerts/)를 따른다.

## 백업과 복구

마이그레이션 전과 정기적으로 원격 D1을 별도 암호화 저장소에 export한다.

```bash
cd worker
npx wrangler d1 export radio-epg --remote --output '<BACKUP_PATH>/radio-epg.sql'
```

복구 연습은 운영 DB에 직접 하지 말고 새 D1 database를 만든 뒤 export를 적용해 API smoke
테스트를 수행한다. D1의 Time Travel 보존 기간은 plan에 따라 다르므로 장기 백업을 대체하지
않는다.

## 문제 해결

### `401 unauthorized` 또는 수집 전체 실패

Worker의 `INGEST_TOKEN`과 GitHub `EPG_INGEST_TOKEN`이 같은지 확인하되 값을 로그에
출력하지 않는다. 하나를 바꿨다면 둘 다 회전하고 수동 `workflow_dispatch`를 실행한다.
Collector는 오류 응답 본문과 token을 진단 결과에 포함하지 않는다.

### D1 migration 또는 deploy 권한 오류

`CLOUDFLARE_ACCOUNT_ID`가 D1 소유 계정인지 확인한다. 토큰 범위가 그 계정 하나를 포함하고
`Workers Scripts Edit`, `D1 Edit`를 갖는지 확인한다. 적용된
마이그레이션은 `npx wrangler d1 migrations list DB --remote`로 확인한다. migration 성공
전에 `wrangler deploy`만 재실행하지 않는다.

### 브라우저만 `403 origin_not_allowed`

요청의 `Origin` 값을 브라우저 개발자 도구에서 확인하고 `CORS_ORIGINS`에 scheme, host,
port까지 정확히 추가한 뒤 배포한다. 경로와 trailing slash는 origin에 넣지 않는다.

### 편성이 비거나 stale

`/v1/coverage`와 collection artifact에서 source ID를 찾고 해당 fixture 테스트를 실행한다.
공식 upstream schema가 바뀌었으면 새 응답을 검토해 fixture와 parser를 함께 수정한다.
일시 장애 동안 다른 채널 편성이나 오래된 wiki 값을 최신처럼 만들지 않는다.

### GitHub 예약 실행이 늦거나 누락됨

schedule workflow가 default branch에 있는지, Actions가 활성화되어 있는지 확인한다.
GitHub의 부하 지연은 오류가 아닐 수 있으므로 `workflow_dispatch`로 한 번 실행하고 결과를
확인한다. 같은 수집이 이미 실행 중이면 concurrency가 두 번째 실행을 대기시킨다.
