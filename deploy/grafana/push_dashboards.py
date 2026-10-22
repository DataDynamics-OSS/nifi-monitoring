#!/usr/bin/env python3
"""NiFi 대시보드를 생성해 Grafana HTTP API로 올립니다(provisioning 파일을 둘 수 없을 때).

    python3 push_dashboards.py --grafana https://grafana.example.com \\
        --token-file ~/.grafana-token \\
        --provenance-url https://nifi-provenance.example.com \\
        [--prometheus-url http://prometheus.example.com:9090] [--timezone Asia/Seoul]

한 번에 처리하는 것:
  1. build_dashboards.py로 대시보드 6개를 메모리에서 생성하고, Provenance 링크 주소
     (숨은 상수 변수 provenance_url)와 시간대를 지정값으로 바꿉니다. dashboards/*.json은
     건드리지 않습니다.
  2. --prometheus-url을 주면 uid "prometheus"인 Prometheus 데이터소스를 만들거나 주소를
     고칩니다(Admin 권한). 주지 않으면 그 uid의 데이터소스가 있는지만 확인합니다.
  3. 폴더 NiFi를 만들고(이미 있으면 그대로) 대시보드를 같은 uid로 덮어씁니다(Editor 권한).
  4. 올린 대시보드를 다시 읽어 폴더와 provenance_url 값을 확인합니다.

인증은 둘 중 하나입니다.
  - 서비스 계정 토큰: --token, --token-file(한 줄), 환경 변수 GRAFANA_TOKEN
  - 사용자명·비밀번호(Basic): --username + --password 또는 --password-file(한 줄, exporter의
    password_file과 같은 양식), 환경 변수 GRAFANA_USER·GRAFANA_PASSWORD.
    --user 이름:비밀번호 한 값으로도 됩니다.
Grafana 주소는 --grafana 또는 GRAFANA_URL,
Provenance 주소는 --provenance-url 또는 NIFI_PROVENANCE_URL로 줍니다. Provenance 주소는
Grafana 서버가 아니라 사용자 브라우저가 직접 여는 주소여야 합니다.

provisioning(deploy/grafana/provisioning/)으로 이미 등록된 Grafana에는 올릴 수 없습니다
(Grafana가 provisioned 대시보드의 API 저장을 거부합니다). API로 올린 대시보드는 화면에서
고칠 수 있지만 git의 build_dashboards.py가 원본이므로, 고친 뒤 다시 실행하면 덮어씁니다.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_dashboards as bd

FOLDER_UID = "nifi"


class Grafana:
    def __init__(self, url: str, auth: str, ctx: ssl.SSLContext | None) -> None:
        self.url = url.rstrip("/")
        self.auth = auth
        self.ctx = ctx

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        """상태 코드와 JSON 본문을 돌려줍니다. 연결 실패는 바로 종료합니다."""
        req = urllib.request.Request(
            self.url + path,
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={
                "Authorization": self.auth,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30, context=self.ctx) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"message": raw.decode(errors="replace")[:300]}
        except urllib.error.URLError as e:
            sys.exit(f"Grafana에 연결할 수 없습니다: {self.url} ({e.reason})")

    def get(self, path: str) -> tuple[int, Any]:
        return self.request("GET", path)


def message(body: Any) -> str:
    if isinstance(body, dict):
        return str(body.get("message") or body.get("error") or body)
    return str(body)


# -- 1. 생성 ----------------------------------------------------------------------


def replace_datasource(node: Any, uid: str) -> Any:
    """build_dashboards.DS(uid "prometheus") 참조를 지정한 uid로 바꿉니다."""
    if isinstance(node, dict):
        if node == bd.DS:
            return {"type": "prometheus", "uid": uid}
        return {k: replace_datasource(v, uid) for k, v in node.items()}
    if isinstance(node, list):
        return [replace_datasource(v, uid) for v in node]
    return node


def render(provenance_url: str, timezone: str | None, datasource_uid: str) -> list[dict]:
    dashboards = []
    for build in bd.BUILDERS.values():
        d = build()
        for var in d["templating"]["list"]:
            if var["name"] == "provenance_url":
                var["query"] = provenance_url
        if timezone:
            d["timezone"] = timezone
        if datasource_uid != bd.DS["uid"]:
            d = replace_datasource(d, datasource_uid)
        dashboards.append(d)
    return dashboards


# -- 2. 데이터소스 -------------------------------------------------------------------


def ensure_datasource(g: Grafana, args: argparse.Namespace) -> str:
    uid = args.datasource_uid
    status, existing = g.get(f"/api/datasources/uid/{uid}")
    if status not in (200, 404):
        sys.exit(f"데이터소스 조회 실패 (HTTP {status}): {message(existing)}")

    if not args.prometheus_url:
        if status == 404:
            sys.exit(
                f"uid '{uid}'인 데이터소스가 없습니다. --prometheus-url로 만들거나 "
                "--datasource-uid로 기존 Prometheus 데이터소스의 uid를 지정하세요"
            )
        if existing.get("type") != "prometheus":
            sys.exit(f"uid '{uid}'인 데이터소스는 Prometheus가 아닙니다: {existing.get('type')}")
        return f"데이터소스 {existing['name']} (uid {uid}, {existing.get('url')}) 사용"

    body = {
        "name": existing.get("name", args.datasource_name)
        if status == 200
        else args.datasource_name,
        "uid": uid,
        "type": "prometheus",
        "access": "proxy",
        "url": args.prometheus_url,
        "jsonData": {"timeInterval": "15s"},  # provisioning/datasources/prometheus.yaml과 같습니다
    }
    if status == 200:
        body["isDefault"] = existing.get("isDefault", False)
        if existing.get("url") == args.prometheus_url:
            return f"데이터소스 {body['name']} (uid {uid}) 이미 같은 주소"
        code, resp = g.request("PUT", f"/api/datasources/uid/{uid}", body)
        action = "주소 변경"
    else:
        code, listing = g.get("/api/datasources")
        if code != 200:
            sys.exit(f"데이터소스 목록 조회 실패 (HTTP {code}): {message(listing)}")
        body["isDefault"] = not any(ds.get("isDefault") for ds in listing)
        code, resp = g.request("POST", "/api/datasources", body)
        action = "생성"
    if code != 200:
        hint = ""
        if code == 403:
            hint = " (데이터소스 생성·수정은 Admin 권한이 필요합니다)"
        elif code == 409:
            hint = " (같은 이름의 데이터소스가 있습니다. --datasource-name을 바꾸세요)"
        sys.exit(f"데이터소스 {action} 실패 (HTTP {code}): {message(resp)}{hint}")
    return f"데이터소스 {body['name']} (uid {uid}) {action}: {args.prometheus_url}"


# -- 3. 폴더와 대시보드 ---------------------------------------------------------------


def ensure_folder(g: Grafana, title: str) -> tuple[str, str]:
    status, folder = g.get(f"/api/folders/{FOLDER_UID}")
    if status == 200:
        return folder["uid"], f"폴더 {folder['title']} (uid {folder['uid']}) 사용"
    if status != 404:
        sys.exit(f"폴더 조회 실패 (HTTP {status}): {message(folder)}")
    code, resp = g.request("POST", "/api/folders", {"uid": FOLDER_UID, "title": title})
    if code == 200:
        return resp["uid"], f"폴더 {title} (uid {resp['uid']}) 생성"
    if code == 409 or code == 412:
        code, listing = g.get("/api/folders")
        for folder in listing if code == 200 else []:
            if folder.get("title") == title:
                return folder["uid"], f"폴더 {title} (uid {folder['uid']}) 사용"
    sys.exit(f"폴더 생성 실패 (HTTP {code}): {message(resp)}")


def push(g: Grafana, dashboard: dict, folder_uid: str) -> str:
    body = {
        "dashboard": dict(dashboard, id=None),
        "folderUid": folder_uid,
        "overwrite": True,
        "message": f"push_dashboards.py {dt.datetime.now().isoformat(timespec='seconds')}",
    }
    code, resp = g.request("POST", "/api/dashboards/db", body)
    if code != 200:
        hint = ""
        if "provision" in message(resp).lower():
            hint = (
                " (provisioning으로 등록된 대시보드는 API로 덮어쓸 수 없습니다. "
                "provisioning 파일을 빼고 Grafana를 재시작하거나 파일을 교체하세요)"
            )
        elif code == 403:
            hint = " (대시보드 저장은 Editor 권한이 필요합니다)"
        sys.exit(f"{dashboard['uid']} 저장 실패 (HTTP {code}): {message(resp)}{hint}")
    return f"{dashboard['uid']} 저장 (version {resp.get('version')}) {g.url}{resp.get('url', '')}"


# -- 4. 확인 ----------------------------------------------------------------------


def verify(g: Grafana, dashboard: dict, folder_uid: str, provenance_url: str) -> list[str]:
    uid = dashboard["uid"]
    status, body = g.get(f"/api/dashboards/uid/{uid}")
    if status != 200:
        return [f"{uid}: 다시 읽지 못했습니다 (HTTP {status}): {message(body)}"]
    problems = []
    if body["meta"].get("folderUid") != folder_uid:
        problems.append(f"{uid}: 폴더가 다릅니다 ({body['meta'].get('folderUid')})")
    constants = {
        v["name"]: v.get("query")
        for v in body["dashboard"]["templating"]["list"]
        if v["type"] == "constant"
    }
    if "provenance_url" in constants and constants["provenance_url"] != provenance_url:
        problems.append(f"{uid}: provenance_url이 다릅니다 ({constants['provenance_url']})")
    if body["dashboard"].get("title") != dashboard["title"]:
        problems.append(f"{uid}: 제목이 다릅니다 ({body['dashboard'].get('title')})")
    return problems


# -- 실행 ----------------------------------------------------------------------------


def auth_header(args: argparse.Namespace) -> str:
    token = args.token or os.environ.get("GRAFANA_TOKEN")
    if args.token_file:
        token = Path(args.token_file).read_text().strip()

    username = args.username or os.environ.get("GRAFANA_USER")
    password = args.password or os.environ.get("GRAFANA_PASSWORD")
    if args.password_file:
        password = Path(args.password_file).read_text().strip()
    if args.user:
        if ":" not in args.user:
            sys.exit("--user는 이름:비밀번호 형식입니다")
        username, password = args.user.split(":", 1)

    if token and (username or password):
        sys.exit("토큰과 사용자명·비밀번호 중 하나만 지정하세요")
    if token:
        return f"Bearer {token}"
    if username and password:
        return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
    if username or password:
        sys.exit("사용자명과 비밀번호를 모두 지정하세요 (--username과 --password/--password-file)")
    sys.exit(
        "인증이 없습니다: 토큰(--token, --token-file, GRAFANA_TOKEN) 또는 "
        "사용자명·비밀번호(--username, --password/--password-file, GRAFANA_USER/GRAFANA_PASSWORD)"
    )


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--grafana", default=os.environ.get("GRAFANA_URL"), help="Grafana 주소 (GRAFANA_URL)"
    )
    ap.add_argument("--token", help="서비스 계정 토큰 (GRAFANA_TOKEN)")
    ap.add_argument("--token-file", help="토큰을 담은 파일 (한 줄)")
    ap.add_argument("--username", help="Basic 인증 사용자명 (GRAFANA_USER)")
    ap.add_argument("--password", help="Basic 인증 비밀번호 (GRAFANA_PASSWORD)")
    ap.add_argument("--password-file", help="비밀번호를 담은 파일 (한 줄, password_file 양식)")
    ap.add_argument("--user", help="Basic 인증을 이름:비밀번호 한 값으로 (예: admin:비밀번호)")
    ap.add_argument(
        "--provenance-url",
        default=os.environ.get("NIFI_PROVENANCE_URL"),
        help="사용자 브라우저가 여는 nifi-provenance-query 주소 (NIFI_PROVENANCE_URL)",
    )
    ap.add_argument(
        "--prometheus-url",
        default=os.environ.get("PROMETHEUS_URL"),
        help="주면 Prometheus 데이터소스를 만들거나 주소를 고칩니다 (PROMETHEUS_URL, Admin 권한)",
    )
    ap.add_argument(
        "--datasource-uid", default=bd.DS["uid"], help="Prometheus 데이터소스 uid (기본 prometheus)"
    )
    ap.add_argument(
        "--datasource-name", default="Prometheus", help="데이터소스를 새로 만들 때 이름"
    )
    ap.add_argument("--folder", default="NiFi", help="대시보드 폴더 이름 (uid는 nifi)")
    ap.add_argument(
        "--timezone", help="대시보드 시간대 (예: Asia/Seoul). 기본은 사용자 브라우저(browser)"
    )
    ap.add_argument("--ca-file", help="Grafana가 사설 CA 인증서를 쓰면 그 CA 파일")
    ap.add_argument("--insecure", action="store_true", help="Grafana 인증서 검증을 건너뜁니다")
    ap.add_argument(
        "--dry-run", action="store_true", help="생성만 하고 Grafana에는 접속하지 않습니다"
    )
    args = ap.parse_args()
    if not args.provenance_url:
        sys.exit("--provenance-url 또는 NIFI_PROVENANCE_URL이 필요합니다 (브라우저가 여는 주소)")
    args.provenance_url = args.provenance_url.rstrip("/")
    if not args.dry_run and not args.grafana:
        sys.exit("--grafana 또는 GRAFANA_URL이 필요합니다")
    return args


def main() -> None:
    args = parse_args()
    dashboards = render(args.provenance_url, args.timezone, args.datasource_uid)
    print(f"대시보드 {len(dashboards)}개 생성: " + ", ".join(d["uid"] for d in dashboards))
    print(f"  provenance_url = {args.provenance_url}")
    print(f"  timezone       = {args.timezone or 'browser'}")
    print(f"  datasource uid = {args.datasource_uid}")
    if args.dry_run:
        print("--dry-run: Grafana에 올리지 않았습니다")
        return

    ctx = None
    if args.insecure:
        ctx = ssl._create_unverified_context()  # 사용자가 --insecure를 명시한 경우만
    elif args.ca_file:
        ctx = ssl.create_default_context(cafile=args.ca_file)
    g = Grafana(args.grafana, auth_header(args), ctx)

    status, body = g.get("/api/folders")
    if status == 401 or status == 403:
        sys.exit(f"Grafana 인증 실패 (HTTP {status}): {message(body)}")
    if status != 200:
        sys.exit(f"Grafana 응답 이상 (HTTP {status}): {message(body)}")

    print(ensure_datasource(g, args))
    folder_uid, note = ensure_folder(g, args.folder)
    print(note)
    for d in dashboards:
        print(push(g, d, folder_uid))

    problems = [p for d in dashboards for p in verify(g, d, folder_uid, args.provenance_url)]
    if problems:
        sys.exit("확인 실패:\n  " + "\n  ".join(problems))
    print(
        f"확인 완료: 폴더 {args.folder}에 대시보드 {len(dashboards)}개, "
        f"provenance_url = {args.provenance_url}"
    )


if __name__ == "__main__":
    main()
