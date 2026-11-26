import { execFile } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const composeFile = fileURLToPath(new URL('../../VERSE/docker-compose.yml', import.meta.url))
const compose = args => new Promise(resolve => {
  execFile('docker', ['compose', '-f', composeFile, ...args], (error, stdout, stderr) => {
    resolve({ status: error ? 1 : 0, stdout, stderr, error })
  })
})
const gpuWorkers = [
  ['worker-surfgen', '/opt/conda/envs/surfgen/bin/python'],
  ['worker-delete', 'python3'],
  ['worker-ecloudgen', 'python'],
  ['worker-epso', 'python'],
  ['worker-tarpass', 'python'],
]
console.log('Starting backend and model workers, checking Agent routes and CUDA...')
const started = await compose([
  'up', '-d', '--wait', '--wait-timeout', '120',
  'backend-api', 'backend-worker', 'workflow-worker', 'dispatcher',
  'worker-protein-preparation', ...gpuWorkers.map(([service]) => service),
])
if (started.status !== 0) {
  console.error('Backend startup failed.')
  console.error(started.stdout || '', started.stderr || '', started.error?.message || '')
  process.exit(1)
}

const agentCheckPromise = compose(['exec', '-T', 'backend-api', 'python', '-c', `
import json
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:18000/openapi.json', timeout=10) as response:
    paths = json.load(response)['paths']
for path, method in [('/runtime', 'get'), ('/workflows', 'get'), ('/plan', 'post'), ('/sessions', 'get'), ('/sessions', 'post')]:
    assert method in paths.get('/api/v1/agent' + path, {}), f'Missing Agent route: {method.upper()} /api/v1/agent{path}'
from uuid import uuid4
from backend.db import SessionLocal
from backend.models import User
from backend.routers.agent_sessions import list_sessions
from backend.services.workflows import list_owner_workflows
with SessionLocal() as db:
    owner_id = uuid4()
    list_owner_workflows(db, owner_id, limit=1)
    list_sessions(limit=1, db=db, user=User(id=owner_id))
`])

const checks = await Promise.all(gpuWorkers.map(async ([service, python]) => {
  const code = service === 'worker-tarpass'
    ? "import ctypes; result = ctypes.CDLL('libcuda.so.1').cuInit(0); assert result == 0, f'CUDA initialization failed: {result}'"
    : "import torch; assert torch.cuda.is_available(), 'CUDA unavailable'; torch.zeros(1, device='cuda'); torch.cuda.synchronize()"
  const check = ['exec', '-T', service, python, '-c', code]
  let result = await compose(check)
  if (result.status !== 0) {
    const recreated = await compose(['up', '-d', '--force-recreate', '--no-deps', service])
    if (recreated.status !== 0) {
      console.error(`${service}: GPU worker recreation failed.`)
      console.error(recreated.stdout || '', recreated.stderr || '', recreated.error?.message || '')
      return false
    }
    result = await compose(check)
  }
  if (result.status !== 0) {
    console.error(`${service}: CUDA is still unavailable. Check the host NVIDIA driver and NVIDIA Container Toolkit.`)
    console.error(result.stdout || '', result.stderr || '', result.error?.message || '')
    return false
  }
  return true
}))
const agentCheck = await agentCheckPromise
if (agentCheck.status !== 0) {
  console.error('Agent API readiness check failed.')
  console.error(agentCheck.stdout || '', agentCheck.stderr || '', agentCheck.error?.message || '')
  process.exit(1)
}
if (checks.some(ok => !ok)) process.exit(1)
console.log('Backend, Agent API and CUDA ready.')
