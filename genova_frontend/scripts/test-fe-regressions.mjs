// Targeted tests for browser-independent state; use the same source modules as the workbench.
// Run with node --test scripts/test-fe-regressions.mjs.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const vue = require('vue')
const settle = () => new Promise(resolve => setImmediate(resolve))
function storage() {
  const values = new Map()
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)), removeItem: key => values.delete(key) }
}
function load(relative, dependencies, globals) {
  const path = fileURLToPath(new URL(relative, import.meta.url))
  const code = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  const exports = {}
  vm.runInNewContext(code, { exports, require: key => dependencies[key] ?? require(key), ...globals }, { filename: path })
  return exports
}
function deferred() {
  let resolve, reject
  const promise = new Promise((a, b) => { resolve = a; reject = b })
  return { promise, resolve, reject }
}

test('FE-29 drafts and attachments stay keyed to account and conversation', async () => {
  const localStorage = storage()
  const storedFiles = new Map()
  // IDB's asynchronous structured clone is represented by an independent store shared by fresh tabs.
  const objectStore = {
    put: (value, key) => storedFiles.set(key, structuredClone(value)),
    delete: key => storedFiles.delete(key),
    get: key => {
      const request = {}
      queueMicrotask(() => { request.result = structuredClone(storedFiles.get(key)); request.onsuccess() })
      return request
    },
  }
  const indexedDB = {
    open: () => {
      const request = {}
      queueMicrotask(() => {
        request.result = { transaction: () => ({ objectStore: () => objectStore }) }
        request.onsuccess()
      })
      return request
    },
  }
  const tab = () => load('../src/utils/agentDraft.ts', {}, { localStorage, indexedDB })
  const first = tab()
  const key = (owner, conversation) => first.agentDraftKey(owner, 'main', conversation)
  const guest = {text:'guest text', files:{attachment:{name:'fixture.txt', file:new Blob(['fixture']), datasetId:'guest-file'}}, context:'', request:null, clientId:'g', saved_at:1}
  first.saveAgentDraft(key('guest-id','session-a'), guest)
  await settle()
  const second = tab()
  assert.equal(await second.readAgentDraft(key('member-id','session-a')), null)
  assert.equal(await second.readAgentDraft(key('guest-id','session-b')), null)
  second.saveAgentDraft(key('member-id','session-a'), {text:'member text',files:{},context:'',request:null,clientId:'m',saved_at:2})
  await settle()
  for (let i=0; i<2; i++) {
    const restoredGuest = await tab().readAgentDraft(key('guest-id','session-a'))
    assert.equal(restoredGuest.text, 'guest text')
    assert.equal(restoredGuest.files.attachment.datasetId, 'guest-file')
    assert.equal(await restoredGuest.files.attachment.file.text(), 'fixture')
    assert.equal((await tab().readAgentDraft(key('member-id','session-a'))).text, 'member text')
  }
})

test('FE-18 synchronous submission lock and original payload survive lost response', async () => {
  const sessionStorage = storage(), requests = []
  let unique = 0
  const { useJobSubmission } = load('../src/composables/useJobSubmission.ts', {
    vue,
    '@/api/genovaBackend': { createBackendJob: (payload, key) => { const d = deferred(); requests.push({payload,key,d}); return d.promise } },
    '@/utils/uuid': { randomUUID: () => String(++unique) },
    '@/utils/guestSession': { readStoredUserInfo: () => ({id:'qa-account'}) },
  }, {sessionStorage})
  const { sendJob, pendingSubmission, confirmedJob } = useJobSubmission('fixture')
  const payload = {job_type:'fixture',params:{count:100}}
  const first = sendJob(payload)
  const doubleClick = sendJob(payload)
  assert.equal(first, doubleClick)
  assert.equal(requests.length, 1)
  requests[0].d.reject(new Error('response lost'))
  await assert.rejects(first)
  payload.params.count = 200
  const retry = sendJob()
  assert.equal(requests[1].key, requests[0].key)
  assert.equal(requests[1].payload.params.count, 100)
  requests[1].d.resolve({data:{id:'job-one'}})
  await retry
  assert.equal(confirmedJob.value, 'job-one')
  assert.equal(pendingSubmission.value, null)
  const next = sendJob(payload)
  assert.notEqual(requests[2].key, requests[0].key)
  assert.equal(requests[2].payload.params.count, 200)
  requests[2].d.reject({response:{status:422}})
  await assert.rejects(next)
  assert.equal(pendingSubmission.value, null)
})

test('FE-26 reconnect discards a late snapshot and failed polls keep retrying', async () => {
  const window = new EventTarget(), document = Object.assign(new EventTarget(), {visibilityState:'visible'})
  const requests=[], timers=[]
  const {subscribeJobList, jobPollDelay} = load('../src/utils/jobListPoller.ts', {
    '@/api/genovaBackend': {listBackendJobs: () => {const d=deferred();requests.push(d);return d.promise}},
    '@/utils/guestSession': {readStoredUserInfo: () => ({id:'qa-account'}),AUTH_EPOCH_KEY:'epoch',AUTH_USER_INFO_KEY:'owner'},
  }, {window,document,setTimeout:(fn,delay)=>{timers.push({fn,delay});return timers.length},clearTimeout:()=>{}})
  const seen=[],errors=[]
  const subscription=subscribeJobList({update:rows=>seen.push(rows),error:error=>errors.push(error)})
  assert.equal(requests.length,1)
  window.dispatchEvent(new Event('genova:connection-restored'))
  requests[0].resolve({data:[{id:'fixture',status:'running'}]})
  await settle()
  assert.equal(seen.length,0)
  assert.equal(requests.length,2)
  requests[1].resolve({data:[{id:'fixture',status:'canceled'}]})
  await settle()
  assert.equal(seen[0][0].status,'canceled')
  const pending=subscription.refresh()
  requests[2].reject(new Error('offline'))
  await pending
  assert.equal(errors.length,1)
  assert.equal(timers.at(-1).delay,jobPollDelay(1))
  timers.at(-1).fn()
  assert.equal(requests.length,4)
  requests[3].resolve({data:[{id:'fixture',status:'canceled'}]})
  await settle()
  assert.equal(timers.at(-1).delay,jobPollDelay(0))
  subscription.stop()
})
