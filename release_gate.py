#!/usr/bin/env python3
"""One-command, fail-fast lifecycle gate for testing_rack."""
import json, os, socket, subprocess, sys, tempfile, time
from pathlib import Path

ROOT=Path(__file__).parent; PY=ROOT/".venv/bin/python"; PORT=18877
results=[]
def run(name, command, env=None):
  started=time.monotonic(); process=subprocess.run(command,cwd=ROOT,text=True,capture_output=True,env=env)
  results.append({"name":name,"passed":process.returncode==0,"seconds":round(time.monotonic()-started,3),"output":(process.stdout+process.stderr)[-4000:]})
  if process.returncode: raise RuntimeError(f"{name} failed\n{results[-1]['output']}")

def wait_port():
  deadline=time.monotonic()+10
  while time.monotonic()<deadline:
    try:
      with socket.create_connection(("127.0.0.1",PORT),.2): return
    except OSError: time.sleep(.05)
  raise RuntimeError("acceptance server did not start")

def main():
  process=None
  try:
    run("syntax",["node","--check","static/app.js"])
    run("coverage-erase",[str(PY),"-m","coverage","erase"])
    coverage_env={**os.environ,"TESTING_RACK_COVERAGE":"1"}
    run("unit-api-virtual",[str(PY),"-m","coverage","run","--parallel-mode","--branch","--source=testing_rack","-m","unittest","-v","test_testing_rack.py","test_http_api.py","test_virtual_integration.py"],coverage_env)
    run("coverage-combine",[str(PY),"-m","coverage","combine"])
    run("coverage",[str(PY),"-m","coverage","report","--fail-under=80"])
    run("model-state-machine",[str(PY),"-m","unittest","-v","test_state_machine.py"])
    with tempfile.TemporaryDirectory(prefix="testing-rack-gate-") as directory:
      state=Path(directory)/"state.json"; secret=Path(directory)/"secret"
      run("initialize",[str(PY),"testing_rack.py","init","--state",str(state),"--secret",str(secret)])
      process=subprocess.Popen([str(PY),"testing_rack.py","serve","--state",str(state),"--secret",str(secret),"--bind","127.0.0.1","--port",str(PORT)],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT)
      wait_port(); run("real-chrome",[str(PY),"browser_acceptance.py","--url",f"http://127.0.0.1:{PORT}"])
    run("diff-whitespace",["git","diff","--check"])
  except Exception as exc:
    report={"passed":False,"error":str(exc),"checks":results}
    print(json.dumps(report,indent=2)); return 1
  finally:
    if process is not None:
      process.terminate()
      try: process.wait(3)
      except subprocess.TimeoutExpired: process.kill(); process.wait()
  report={"passed":True,"checks":results,"finished_at":time.time()}
  (ROOT/"release-gate-report.json").write_text(json.dumps(report,indent=2)+"\n")
  print(json.dumps(report,indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())
