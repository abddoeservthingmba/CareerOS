import json, io
# (id, track, phase, module, requires)
R1,R2,R3="R1","R2","R3"
D=[]
def a(i,t,p,m,req,**kw): D.append(dict(id=i,track=t,phase=p,module=m,requires=req,**kw))

# ---- foundations (P0 unless noted)
for i,req in [("FOUND-01",[]),("FOUND-02",["FOUND-01"]),("FOUND-03",["FOUND-01"]),("FOUND-04",["FOUND-01"]),
              ("FOUND-05",["FOUND-04"]),("FOUND-06",["FOUND-01"]),("FOUND-07",["FOUND-03","DATA-03"]),
              ("FOUND-08",["FOUND-02","FOUND-12"]),("FOUND-09",["FOUND-05"]),("FOUND-10",["FOUND-02","FOUND-09"]),
              ("FOUND-11",["FOUND-10","FOUND-12"]),("FOUND-12",["FOUND-02"]),("FOUND-13",["FOUND-05","FOUND-12"]),
              ("FOUND-14",["FOUND-02"]),("FOUND-15",["FOUND-02","FOUND-13"]),("FOUND-16",["FOUND-02","FOUND-12"])]:
    a(i,R1,"P0","core",req)
# ---- data model
for i,req in [("DATA-01",["FOUND-03"]),("DATA-02",["DATA-01"]),("DATA-03",["DATA-02"]),("DATA-04",["FOUND-02"]),
              ("DATA-05",["DATA-02","FOUND-10"]),("DATA-06",["FOUND-03"]),("DATA-07",["DATA-02"])]:
    a(i,R1,"P0","core",req)
# ---- ai layer
for i,req in [("AI-01",["FOUND-03"]),("AI-02",["AI-01","FOUND-02"]),("AI-03",["AI-02","FOUND-10","DATA-02"]),
              ("AI-04",["AI-02","DATA-02"]),("AI-05",["AI-02","FOUND-02"]),("AI-06",["AI-01"]),("AI-07",["AI-01","FOUND-02"])]:
    a(i,R1,"P0","ai",req)
# ---- dependency spec itself
for i in ["DEP-01","DEP-02","DEP-03","DEP-04","DEP-05","DEP-06"]:
    a(i,R1,"P0","core",["FOUND-06"])
# ---- auth
a("AUTH-01",R1,"P1","auth",["FOUND-02","FOUND-12","FOUND-16","DATA-02","AUTH-09"],writes_collections=["users","email_tokens"])
a("AUTH-02",R1,"P1","auth",["AUTH-01"])
a("AUTH-03",R1,"P1","auth",["AUTH-01","FOUND-16"])
a("AUTH-04",R1,"P1","auth",["AUTH-01","FOUND-03"],writes_collections=["refresh_tokens"])
a("AUTH-05",R1,"P1","auth",["AUTH-01","FOUND-16"])
a("AUTH-06",R2,"S3","auth",["AUTH-04"])
a("AUTH-07",R1,"P1","auth",["AUTH-01","DATA-04","DATA-05","FOUND-10","FOUND-16"])
a("AUTH-08",R2,"S3","auth",["AUTH-07","DATA-04","FOUND-08"])
a("AUTH-09",R1,"P1","auth",["FOUND-02","FOUND-10"])
a("AUTH-10",R1,"P1","auth",["AUTH-04","DATA-01","FOUND-13"])
# ---- profile
a("PROF-01",R1,"P2","profile",["DATA-02","FOUND-09","DATA-06"],publishes_events=["ProfileUpdated","ProfileConfirmed"])
a("PROF-02",R1,"P2","profile",["PROF-01","FOUND-03"])
a("PROF-03",R1,"P2","profile",["PROF-01"])
a("PROF-04",R3,None,"profile",["PROF-01","RES-01"])
a("PROF-05",R2,"S3","profile",["PROF-01","PROF-02"])
a("PROF-06",R1,"P2","profile",["PROF-01","DATA-02"])
a("PROF-07",R2,"S3","profile",["PROF-01","DATA-02"])
# ---- resume
a("RES-01",R1,"P2","resume",["AUTH-03","DATA-04","FOUND-08"])
a("RES-02a",R1,"P2","resume",["RES-01"])
a("RES-02b",R2,"S3","resume",["RES-02a"])
a("RES-03",R1,"P2","resume",["RES-02a","AI-01","AI-06","AI-07","PROF-06"],publishes_events=["ResumeExtracted"])
a("RES-04",R2,"S3","resume",["RES-03"])
a("RES-05",R1,"P2","resume",["RES-01","DATA-04","AI-01"])
a("RES-06",R1,"P2","resume",["RES-01","FOUND-10","FOUND-11"])
a("RES-07",R2,"S3","resume",["RES-03","PROF-03"])
# ---- jobs / connectors
a("CONN-01",R1,"P3","connectors",["FOUND-03","DATA-02"])
a("CONN-02",R1,"P3","connectors",["CONN-01","FOUND-04"])
a("CONN-03",R1,"P3","connectors",["CONN-01","FOUND-10","FOUND-02"])
a("CONN-04",R1,"P3","connectors",["CONN-01"])
a("CONN-05",R1,"P3","connectors",["CONN-01","DATA-05"])
a("CONN-06a",R1,"P3","connectors",["CONN-01","CONN-04"])
a("CONN-06b",R2,"S2","connectors",["CONN-06a"])
a("CONN-07",R1,"P3","connectors",["CONN-04","WEB-03","MOB-03"])
a("JOB-01",R1,"P3","jobs",["DATA-02","CONN-01"])
a("JOB-02",R1,"P3","jobs",["JOB-01","CONN-03","FOUND-10","PROF-02"],publishes_events=["JobsIngested"])
a("JOB-03",R1,"P3","jobs",["JOB-01","DATA-03"])
a("JOB-04",R1,"P3","jobs",["JOB-01"])
a("JOB-05",R1,"P3","jobs",["JOB-04","PROF-06","AI-03","DATA-06"])
a("JOB-06",R1,"P3","jobs",["JOB-04","DATA-03","FOUND-07"])
a("JOB-07",R2,"S2","jobs",["JOB-06"])
a("JOB-08",R1,"P3","jobs",["JOB-02","DATA-05"],publishes_events=["JobExpired"])
a("JOB-09",R1,"P3","jobs",["JOB-06","DATA-02"])
a("JOB-10",R2,"S2","jobs",["JOB-09","ADMIN-05"])
# ---- matching
a("MATCH-01",R1,"P4","matching",["PROF-02","PROF-06","JOB-04","JOB-05","DATA-02"])
a("MATCH-02a",R1,"P4","matching",["MATCH-01"])
a("MATCH-02b",R1,"P4","matching",["MATCH-02a","AI-03","AI-07","ADMIN-03"],enabled_in="R2")
a("MATCH-03",R1,"P4","matching",["MATCH-01","FOUND-02"])
a("MATCH-04",R1,"P4","matching",["AI-02","DATA-06","PROF-01","JOB-05"])
a("MATCH-05",R1,"P4","matching",["MATCH-01","MATCH-04","FOUND-09","FOUND-10","DATA-03"],
  consumes_events=["JobsIngested","ProfileUpdated"],writes_collections=["match_scores"])
a("MATCH-06",R2,"S3","matching",["MATCH-05","JOB-09"])
a("MATCH-07",R1,"P4","matching",["MATCH-05","FOUND-07"])
a("MATCH-08",R3,None,"matching",["MATCH-02a","MATCH-06"])
a("MATCH-09",R1,"P4","matching",["MATCH-05","MATCH-07","JOB-06","WEB-03","MOB-03"])
# ---- apply
a("APPLY-01",R1,"P5","apply",["PROF-03","AI-02","DATA-02"])
a("APPLY-02",R1,"P5","apply",["APPLY-01","PROF-03","MATCH-02a","AI-03","AI-06","AI-07","FOUND-08","FOUND-11"])
a("APPLY-03",R1,"P5","apply",["APPLY-02","APPLY-04"],publishes_events=["PackApproved"])
a("APPLY-04",R1,"P5","apply",["APPLY-02","PROF-06"])
a("APPLY-05",R1,"P5","apply",["APPLY-03","TRACK-01","CONN-07"],publishes_events=["AppliedConfirmed"])
a("APPLY-06",R3,None,"apply",["APPLY-05"])
a("APPLY-07",R1,"P5","apply",["DATA-02","FOUND-14"])
a("APPLY-08",R3,None,"apply",["PROF-03","RES-02a"])
a("APPLY-09",R1,"P6","apply",["APPLY-04","AI-03","TRACK-03"])
# ---- tracker
a("TRACK-01",R1,"P5","tracker",["JOB-01","DATA-02","FOUND-09"],publishes_events=["ApplicationStatusChanged"],
  consumes_events=["AppliedConfirmed","JobExpired","PackApproved"])
a("TRACK-02a",R1,"P6","tracker",["TRACK-01","FOUND-07","DATA-03"])
a("TRACK-02b",R2,"S4","tracker",["TRACK-02a","TRACK-03"])
a("TRACK-03",R1,"P6","tracker",["TRACK-01","DATA-04"])
a("TRACK-04",R1,"P6","tracker",["TRACK-01","APPLY-07","NOTIF-05"])
a("TRACK-05",R1,"P6","tracker",["TRACK-01","SEC-02"])
a("TRACK-06",R2,"S4","tracker",["TRACK-01","NOTIF-04"])
a("TRACK-07",R2,"S4","tracker",["TRACK-01"])
# ---- notifications
a("NOTIF-01",R1,"P6","notifications",["TRACK-01","TRACK-03","FOUND-03","DATA-02"])
a("NOTIF-02a",R1,"P6","notifications",["NOTIF-01","FOUND-16","FOUND-11"])
a("NOTIF-02b",R2,"S4","notifications",["NOTIF-02a","MOB-05"])
a("NOTIF-02c",R3,None,"notifications",["NOTIF-02a"])
a("NOTIF-03",R2,"S4","notifications",["NOTIF-01"])
a("NOTIF-04",R2,"S4","notifications",["NOTIF-02a","MATCH-05","JOB-07"])
a("NOTIF-05",R1,"P6","notifications",["NOTIF-01","FOUND-10","DATA-03"])
# ---- admin
a("ADMIN-01",R1,"P3","admin",["CONN-03","DATA-02"])
a("ADMIN-02",R1,"P4","admin",["AI-04","DATA-03"])
a("ADMIN-03",R1,"P4","admin",["FOUND-02","DATA-02"])
a("ADMIN-04",R2,"S2","admin",["PROF-06","JOB-04"])
a("ADMIN-05",R2,"S2","admin",["JOB-10"])
a("ADMIN-06",R1,"P1","admin",["AUTH-10","WEB-01"])
# ---- clients
a("WEB-01",R1,"P0","web",["FOUND-13"])
a("WEB-02",R1,"P1","web",["WEB-01","AUTH-04"])
a("WEB-03",R1,"P2","web",["WEB-01","WEB-02"])
a("WEB-04",R1,"P2","web",["WEB-03","AI-06"])
a("WEB-05",R1,"P4","web",["WEB-03"])
a("WEB-06",R1,"P1","web",["WEB-01","FOUND-12"])
a("WEB-07",R2,"S5","web",["WEB-03"])
a("WEB-08",R1,"P7","web",["WEB-03","WEB-04","AUTH-10"])
a("MOB-01",R1,"P0","mobile",["FOUND-13"])
a("MOB-02",R1,"P1","mobile",["MOB-01","AUTH-04"])
a("MOB-03",R1,"P2","mobile",["MOB-01","MOB-02"])
a("MOB-04",R1,"P2","mobile",["MOB-03"])
a("MOB-05",R1,"P5","mobile",["MOB-03"])
a("MOB-06",R1,"P7","mobile",["MOB-03"])
a("MOB-07",R2,"S4","mobile",["MOB-03"])
a("MOB-08",R1,"P7","mobile",["MOB-03","MOB-04","MOB-06"])
# ---- ops & security
a("OPS-01",R1,"P0","infra",["FOUND-01","FOUND-02"])
a("OPS-02",R1,"P0","infra",["OPS-01"])
a("OPS-03",R1,"P0","infra",["OPS-01","FOUND-06","DEP-04"])
a("OPS-04",R1,"P0","infra",["FOUND-14","OPS-01"])
a("OPS-05",R1,"P0","infra",["FOUND-02"])
a("OPS-06",R1,"P0","infra",["OPS-01","DATA-04"])
a("OPS-07",R2,"S5","infra",["OPS-04","OPS-06"])
a("OPS-08",R1,"P7","infra",["AI-03","OPS-04","ADMIN-03"])
a("SEC-01",R1,"P0","core",["FOUND-04"])
a("SEC-02",R1,"P1","core",["AUTH-04","AUTH-09","AUTH-10","FOUND-14"])
a("SEC-03",R1,"P2","core",["AI-05","AI-06","RES-05"])
a("SEC-04",R1,"P1","core",["AUTH-01","AUTH-07","DATA-05"])
a("SEC-05",R1,"P3","core",["CONN-04","CONN-02"])
a("SEC-06",R1,"P5","core",["APPLY-04","APPLY-05","APPLY-03"])

ids={d["id"] for d in D}
bad=[(d["id"],r) for d in D for r in d["requires"] if r not in ids]
assert not bad, bad
PH=["P0","P1","P2","P3","P4","P5","P6","P7","S1","S2","S3","S4","S5",None]
def pi(p): return PH.index(p)
# checks
track_viol=[]; phase_viol=[]
by={d["id"]:d for d in D}
def closure(i,seen=None):
    seen=seen or set()
    for r in by[i]["requires"]:
        if r not in seen: seen.add(r); closure(r,seen)
    return seen
for d in D:
    if d["track"]=="R1":
        for r in closure(d["id"]):
            if by[r]["track"]!="R1": track_viol.append((d["id"],r,by[r]["track"]))
    for r in d["requires"]:
        if d["phase"] and by[r]["phase"] and pi(by[r]["phase"])>pi(d["phase"]):
            phase_viol.append((d["id"],d["phase"],r,by[r]["phase"]))
print("entries:",len(D))
print("track closure violations:",track_viol or "none")
print("phase closure violations:",phase_viol or "none")
# emit yaml
out=io.StringIO()
out.write("# JobPilot dependency manifest — spec v2.1\n# Authority for build order and closure checks. See docs/spec/18-dependency-closure.md.\n")
for d in sorted(D,key=lambda x:(pi(x["phase"]),x["id"])):
    out.write("\n%s:\n  track: %s\n  phase: %s\n  module: %s\n"%(d["id"],d["track"],d["phase"] or "null",d["module"]))
    if d.get("enabled_in"): out.write("  enabled_in: %s\n"%d["enabled_in"])
    out.write("  requires: [%s]\n"%(", ".join(d["requires"])))
    for k in ("consumes_events","publishes_events","writes_collections"):
        if d.get(k): out.write("  %s: [%s]\n"%(k,", ".join(d[k])))
open("dependencies.yaml","w").write(out.getvalue())
json.dump(D,open("/tmp/claude-0/deps.json","w"))
# build order
order=[];placed=set()
for p in PH:
    pool=[d for d in D if d["phase"]==p]
    while pool:
        prog=[d for d in pool if all(r in placed or by[r]["phase"]==p and r in placed or by[r]["phase"]!=p for r in d["requires"])]
        prog=sorted([d for d in pool if all((r in placed) or (by[r]["phase"]==p and r in placed) for r in d["requires"])],key=lambda x:x["id"])
        if not prog: prog=sorted(pool,key=lambda x:x["id"])[:1]
        for d in prog: order.append(d); placed.add(d["id"]); pool.remove(d)
print("build order first 10:",[d["id"] for d in order[:10]])
open("BUILD-ORDER.md","w").write("# Build order — generated from dependencies.yaml\n\nDo not edit. Regenerate with `make build-order`.\n\n"+
  "\n".join("%3d. `%s` — %s · %s · %s"%(n+1,d["id"],d["phase"] or "unphased",d["track"],d["module"]) for n,d in enumerate(order))+"\n")
