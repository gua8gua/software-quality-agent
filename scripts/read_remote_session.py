"""Read public SDK session items without changing server or model state."""
import json
import os
import shlex
import sys

import paramiko

review_id = sys.argv[1]
code = '''
import json, sqlite3, inspect
from importlib.metadata import version
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from software_quality_agent.config import Settings
s=Settings()
print(json.dumps({"session_db":s.suggestion_session_db,"checkpoint_dir":s.suggestion_checkpoint_dir}))
source=inspect.getsource(OpenAIChatCompletionsModel.get_response)
print(json.dumps({"agents_version":version("openai-agents"),"openai_version":version("openai"),"rejects_empty_length": "produced no assistant text" in source}))
db=sqlite3.connect("file:"+s.suggestion_session_db+"?mode=ro",uri=True)
rows=db.execute("SELECT id,session_id,message_data FROM agent_messages WHERE session_id LIKE ? ORDER BY id DESC LIMIT 180",("%"+REVIEW+"%",)).fetchall()
for key,session,raw in reversed(rows):
 item=json.loads(raw)
 if item.get("type")=="reasoning":continue
 print(json.dumps({"id":key,"session":session,"item":item},ensure_ascii=False))
'''.replace("REVIEW", repr(review_id))
client = paramiko.SSHClient()
client.load_system_host_keys()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    client.connect("10.71.29.93", username="fuxin", password=os.environ["INVENTORY_PASSWORD"], timeout=10)
    command = "docker exec software-quality-current-workbench python -c " + shlex.quote(code)
    _, out, err = client.exec_command(command, timeout=45)
    print(out.read().decode("utf-8"))
    print(err.read().decode("utf-8"), file=sys.stderr)
    sys.exit(out.channel.recv_exit_status())
finally:
    client.close()
