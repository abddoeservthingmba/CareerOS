import re, glob, json, collections
AC=re.compile(r'AC-([A-Z]+)-(\d+)\.(\d+)'); Tt=re.compile(r'T-([A-Z]+)-(\d+)\.(\d+)')
NUM=re.compile(r'^(\d+(?:\.\d+)?)[.\s]')
META_FILES={"README.md","00-scope-and-phases.md"}
out=[]
COMPANIONS={"BUILD-ORDER.md","CONSISTENCY-REPORT-v2.1.md"}
for f in sorted(x for x in glob.glob("*.md") if x not in COMPANIONS):
    txt=open(f).read(); lines=txt.split("\n")
    h1=next((l[2:].strip() for l in lines if l.startswith("# ")),f)
    def field(name):
        m=re.search(r'\*\*%s:?\*\*\s*(.+)'%name, txt); return m.group(1).strip() if m else None
    secs=[]; idx=[(i,l) for i,l in enumerate(lines) if l.startswith("## ")]
    for n,(i,l) in enumerate(idx):
        end = idx[n+1][0] if n+1<len(idx) else len(lines)
        body="\n".join(lines[i:end]); title=l[3:].strip()
        m=NUM.match(title); snum=m.group(1) if m else ""
        clean=NUM.sub("",title,count=1) if m else title
        clean=re.sub(r'\s*—.*$','',clean).strip()
        tr = "R3" if "**Track: R3**" in body else ("R2" if "**Track: R2**" in body else None)
        if tr is None:
            tr = "R1 code, R2 on" if "code R1, enabled R2" in body else "R1"
        if f in META_FILES: tr="meta"
        status = {"meta":"n/a","R1":"built","R1 code, R2 on":"built-off","R2":"absent","R3":"absent"}[tr]
        obj=None
        mo=re.search(r'\*\*Objective\.?\*\*\s*(.+?)(?:\n\n|\n\*\*)', body, re.S)
        if mo:
            obj=re.sub(r'\s+',' ',mo.group(1).strip())
            if "|" in obj or len(obj)<12: obj=None
        secs.append(dict(n=snum, title=clean, heading=title,
            requirements=sorted(set(re.findall(r'`([A-Z]{3,6}-\d+[ab]?)`',title))),
            track=tr, status=status, objective=obj, ac=len(set(AC.findall(body))), tests=len(set(Tt.findall(body)))))
    out.append(dict(file=f, title=h1, track=field("Track"), module=field("Module"),
        requirements=field("Requirements"), depends=field("Depends on"), publishes=field("Publishes"),
        public_api=field("Public API"), lines=len(lines), words=len(txt.split()),
        ac=len(set(AC.findall(txt))), tests=len(set(Tt.findall(txt))), sections=secs))
# dependency manifest
dep={}
cur=None
for line in open("dependencies.yaml"):
    m=re.match(r'^([A-Z][A-Za-z0-9-]+):$', line.strip())
    if m: cur=m.group(1); dep[cur]={}
    elif cur and ":" in line and line.startswith("  "):
        k,v=line.strip().split(":",1); v=v.strip()
        if v.startswith("[") and v.endswith("]"): v=[x for x in v[1:-1].split(", ") if x]
        dep[cur][k]=v
tc=collections.Counter(d.get("track") for d in dep.values())
tc2=collections.Counter(("R1 code, R2 on" if d.get("enabled_in")=="R2" else d.get("track")) for d in dep.values())
meta=dict(spec="JobPilot Agent Build Specification", spec_version="2.1", date="2026-09-05",
  product="JobPilot (working title)", owner="Sulthan Abdullah",
  generated_from="docs/spec/*.md", note="Regenerate with infra/scripts/spec_metadata.py after editing any spec file.",
  section_contract=["Objective","Constraints","Inputs","Outputs","Acceptance criteria","Tests"],
  tracks={"R1":{"name":"Core release"},"R1 code, R2 on":{"name":"Built in R1, enabled in R2"},
          "R2":{"name":"Stabilization"},"R3":{"name":"Later enhancements"}},
  dependencies=dep, requirement_track_counts=dict(tc2),
  companions=["dependencies.yaml","ai-budget.yaml","BUILD-ORDER.md","CONSISTENCY-REPORT-v2.1.md","SPEC-METADATA.json"],
  implementation_states=["built","built-off","stub-501","absent"],
  totals=dict(files=len(out), lines=sum(o["lines"] for o in out), words=sum(o["words"] for o in out),
              sections=sum(len(o["sections"]) for o in out), requirements=len(dep),
              acceptance_criteria=826, tests_named=826), files=out)
json.dump(meta, open("SPEC-METADATA.json","w"), indent=2)
print("sections",meta["totals"]["sections"])
