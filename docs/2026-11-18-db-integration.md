# PostgreSQL 검증 및 문의 영속성 연동

## 작업일지

- DB 서버: `roundup-db-001-a26u`, PostgreSQL 17.11.
- Private 주소: `pg-4c5kmb.vpc-cdb-kr.ntruss.com:5432` (`10.0.1.7`).
- 데이터베이스: `roundup`. 공개 도메인은 미할당.
- 현재 Mac 공인 IP가 변경되어 기존 SSH 규칙으로 접근할 수 없었다.
- 사용자 승인 후 API 서버 ACG에 `<운영자 공인 IP>/32`의 TCP 22와 8787을 추가했다. 기존 제한 규칙은 유지했다.
- DB ACG `cloud-postgresql-2fieuz`에는 서비스 자체 규칙만 있었다. API 서버 `10.0.1.6/32`의 TCP 5432를 추가했고 자동 생성 규칙은 보존했다.
- API 서버에 PostgreSQL 클라이언트를 설치했다. 이후 아래와 같이 저장 API 배포와 앱 연동을 완료했다.

## DB QA

API 서버에서 `psql -X -v ON_ERROR_STOP=1 -1 -At -c ...`로 버전 및 현재 사용자 조회, 고유 이름의 시험 테이블 생성, 한 행 입력, 조회, 삭제를 하나의 트랜잭션에서 실행했다. 암호는 로컬 키체인에서 읽어 SSH 표준입력으로 전달했고 로그에 출력하지 않았다.

```text
PostgreSQL 17.11 on x86_64-pc-linux-gnu
roundup|roundupadmin
CREATE TABLE
INSERT 0 1
1|roundup verification
DROP TABLE
exit 0
```

- 시험 테이블: `_roundup_verify_edd7790ff98743858600a13bbbbd0858`. 트랜잭션 안에서 생성하고 삭제했다.
- `sslmode=require` 접속은 `server does not support SSL, but SSL was required`로 실패했다.
- 이후 명시적인 `sslmode=disable`로 VPC 내부 SQL 검증을 실행했다. `pg_stat_ssl.ssl` 결과는 `f`다. DB TLS가 적용됐다고 주장하지 않는다.
- Mac에서는 도메인이 `10.0.1.7`로 해석되며, 5초 제한 소켓 접속이 `connect_ex=35`로 성공하지 못했다. 이는 현재 Mac 네트워크의 직접 접속 차단 증거이며 모든 외부 네트워크에 대한 실행 검증은 아니다.

## 코드리뷰 및 남은 검증

- 변경 전 `DemoStore`는 앱 시작 시 샘플 문의를 만들고 초안과 승인 상태를 메모리에서 수정했다.
- 변경 전 FastAPI 서버에는 문의 저장 API나 DB 준비 상태 검사가 없었다.
- iOS의 서버 조회, 명시적 초안 저장, 현재 초안을 포함한 승인/반려, revision 충돌 처리 구현은 완료됐다. 기본 실행에서 통신 실패 시 샘플 문의로 대체하지 않는다.
- Core 테스트 19개가 통과했고, iOS Simulator 일반 빌드가 성공했다. 증거는 `/var/folders/1s/9l5jc5rj2lnbtkwzmhmzq5mr0000gn/T/roundup-inquiry-LFMH8C/`의 `core-restored.log`, `build-final.log`다.
- Core 영속성 테스트는 저장소 대역을 사용하므로 실제 PostgreSQL 영속성 증거가 아니다.
- DB 테이블, 저장 API, 실제 서버 배포, 앱 재실행 후 원격 상태 유지, 기존 UI 회귀 테스트를 완료했다.
- DB 인프라 검증 통과를 애플리케이션 영속성 완료로 해석하지 않는다.

## 배포 및 실제 PostgreSQL 통합 결과

- 릴리스: `/opt/roundup/releases/db-1585f055`.
- `/opt/roundup/current`가 위 릴리스를 가리키며 `roundup-api.service`가 이를 실행한다. 이전 서비스 설정은 릴리스의 `previous.service`에 보존했다.
- API 인증키와 IP 인증서 설정은 기존 `/opt/roundup` 파일을 사용한다.
- DB 설정은 릴리스의 `db.env`에 mode 0600으로 저장했다. DB의 TLS 미지원이 확인돼 `DATABASE_SSLMODE=disable`을 명시했다.
- `uv sync --frozen --group dev` 후 실제 DB를 지정한 `uv run --no-sync pytest -q`: **36 passed in 1.68s**. 테스트별 UUID 스키마를 생성/삭제하며 공개 업무 테이블은 건드리지 않는다.
- `uv run --no-sync python init_db.py`: 테이블 생성 및 가상 문의 3건 초기화 성공. 재실행 시 기존 상태를 덮어쓰지 않는다.
  - 당시 실행 기록이다. 지금은 `init_db.py`가 없다. 스키마는 `uv run alembic upgrade head`로 적용하고 초기 데이터가 필요하면 `uv run python seed.py`를 실행한다.
- 배포 후 인증서 검증과 API 키를 적용한 `/health/ready`, `/inquiries`: **200**.
- 실제 API에서 빈 승인 **422**, 없는 문의 수정 **404**, 이미 승인한 문의의 반복 승인 **409**를 확인했다.
- 문의 테이블 저장 트랜잭션, 행 잠금, revision 충돌 검사는 서버 책임이다. 입력은 Pydantic 모델에서 파싱하며 앱은 성공 응답 후 상태를 갱신한다. 승인으로 메시지 발송이나 예약 생성은 수행하지 않는다.

## 실제 앱 QA

- 샘플 실행 인자 없이 iPhone 17 Pro 시뮬레이터에서 실행했다.
- `inquiry-clay` 초안을 앱에서 `DB 저장 확인: 앞치마와 도구를 준비해 드립니다.`로 수정하고 저장했다. 서버 조회에서 revision 1을 확인했다.
- 앱 프로세스를 재실행하고 같은 문의 화면에서 저장된 문장을 확인했다.
- 앱에서 해당 문의를 승인했고, 서버 상태는 `approved`, revision 2가 됐다.
- 재실행 후 대기 문의는 3건에서 2건, 운영 배지는 7에서 6으로 유지됐다.
- `inquiry-change`의 편집 내용을 비운 뒤 승인하면 오류를 표시하고 대기 상태를 유지했다. 이어 빈 초안을 반려했다.
- 재실행 후 승인 1건, 반려 1건, 대기 1건 상태를 확인했다. 대기 문의 1건 및 배지 5가 표시됐다. 이 가상 데이터의 QA 처리 상태는 초기화하지 않았다.
- 기존 UI 테스트 **6/6**, Core 테스트 **19/19**, 실제 DB 포함 백엔드 테스트 **36/36** 통과.
- 증거: `/var/folders/1s/9l5jc5rj2lnbtkwzmhmzq5mr0000gn/T/roundup-db-qa-OrmqPU/`의 `ui-tests.log`, `ui-tests.xcresult`, `draft-restored.png`, `approval-restored.png`, `blank-approval-refused.png`, `decision-state-restored.png`.
- 오프라인/응답 유실/동시 요청은 Core·백엔드 테스트로 검증했다. 모든 장애 상황을 실제 GUI에서 재현했다고 주장하지 않는다.

## 범위와 제한

- 이번에 DB로 연결한 업무 데이터는 문의·초안·승인·반려다. 예약·주문 등 다른 샘플 데이터의 서버 영속화는 포함하지 않았다.
- 실제 iPhone 테스트, DB 백업 복원 훈련, DB TLS 설정은 수행하지 않았다.
- 도메인과 공인 HTTPS 인증서는 사용자 요청대로 보류했다. 앱과 API 사이의 기존 자체 서명 HTTPS 및 인증서 고정은 유지한다.
- 기존 화면의 고정 날짜 등 이번 범위 밖 샘플 표시는 변경하지 않았다.
- 커밋과 푸시는 하지 않았다.
