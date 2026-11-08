"""Command-line key management (run on the machine that hosts the license server).

  python admin.py create --name "Demented" --days 30          # prints a new key
  python admin.py create --name "Friend" --plan pro --devices 2
  python admin.py list
  python admin.py revoke LAST5        python admin.py restore LAST5
  python admin.py reset LAST5         # lets the key be used on a different computer
  python admin.py extend LAST5 --days 30
"""
import argparse
import time

import server as S


def find(c, hint):
    rows = c.execute("SELECT * FROM licenses WHERE key_hint=?", (hint.upper()[-5:],)).fetchall()
    if len(rows) != 1:
        raise SystemExit("No single key ends with that - use the full last 5 characters shown by 'list'.")
    return rows[0]


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    cr = sub.add_parser("create")
    cr.add_argument("--name", default="")
    cr.add_argument("--plan", default="member")
    cr.add_argument("--days", type=int)
    cr.add_argument("--devices", type=int, default=1)
    sub.add_parser("list")
    for n in ("revoke", "restore", "reset", "extend"):
        p = sub.add_parser(n)
        p.add_argument("hint")
        if n == "extend":
            p.add_argument("--days", type=int, default=30)
    a = ap.parse_args()
    c = S.db()
    if a.cmd == "create":
        print(S.make_license(c, a.name, a.plan, a.days, a.devices))
        print("(shown once - copy it now)")
    elif a.cmd == "list":
        for l in S.admin_list(c):
            exp = time.strftime("%Y-%m-%d", time.localtime(l["expires_at"])) if l["expires_at"] else "never"
            print(f"...{l['key_hint']}  {l['label'] or '-':<18} {l['plan']:<8} expires {exp:<11}{' REVOKED' if l['revoked'] else ''}  computers: {', '.join(d['name'] for d in l['devices']) or '-'}")
    else:
        l = find(c, a.hint)
        if a.cmd == "revoke":
            c.execute("UPDATE licenses SET revoked=1 WHERE id=?", (l["id"],))
        elif a.cmd == "restore":
            c.execute("UPDATE licenses SET revoked=0 WHERE id=?", (l["id"],))
        elif a.cmd == "reset":
            c.execute("DELETE FROM devices WHERE license_id=?", (l["id"],))
        elif a.cmd == "extend":
            c.execute("UPDATE licenses SET expires_at=MAX(COALESCE(expires_at,0),?)+? WHERE id=?", (int(time.time()), a.days * 86400, l["id"]))
        c.commit()
        print("done")


if __name__ == "__main__":
    main()
