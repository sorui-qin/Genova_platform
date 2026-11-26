<template>
  <section class="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
    <header class="flex flex-wrap items-center justify-between gap-2"><h3 class="font-semibold">{{ title }}</h3><span class="text-xs text-slate-500">{{ total }} {{ L('条结果','results') }}</span></header>
    <p v-if="loading" role="status" class="text-sm">{{ L('加载结果摘要…','Loading result summary…') }}</p>
    <p v-if="error" role="alert" class="text-sm text-red-700">{{ error }} <Button size="sm" variant="ghost" @click="load">{{ L('重试','Retry') }}</Button></p>
    <p v-if="warning" class="text-sm text-amber-800">{{ warning }}</p>
    <div class="flex gap-3 overflow-x-auto"><button v-for="row in rows" :key="row.id || row.molecule_id" type="button" class="shrink-0 rounded-lg border p-2 text-left hover:bg-slate-50" @click="$emit('open')"><MoleculeViewer :smiles="row.smiles" width="180px" height="130px" /><p class="max-w-44 truncate text-xs">{{ row.molecule_id || row.extra?.rank || row.id }}</p><p v-if="row.metrics?.docked?.affinity != null" class="text-xs">Docked affinity {{ row.metrics.docked.affinity }}</p><p v-if="row.extra?.fitness != null" class="text-xs">Fitness {{ row.extra.fitness }}</p></button></div>
    <footer class="flex flex-wrap gap-2"><Button size="sm" @click="$emit('open')">{{ L('审阅完整结果','Review all results') }}</Button><Button v-if="postprocessing && selectable" size="sm" variant="outline" @click="$emit('select')">{{ L('筛选并保存候选','Select and save candidates') }}</Button></footer>
  </section>
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '@/components/ui/button'
import MoleculeViewer from '@/components/common/MoleculeViewer.vue'
import { getBackendJob, getAgentCandidateSet, listBackendJobResults } from '@/api/genovaBackend'
import request from '@/utils/request'
import { requestErrorKind, displayErrorMessage } from '@/utils/requestError'
const props=defineProps<{jobId:string;title:string;postprocessing?:boolean;selectable?:boolean;candidateSetId?:string;sessionId?:string;recovery?:number}>()
defineEmits<{open:[];select:[]}>()
const { locale }=useI18n(), L=(zh:string,en:string)=>locale.value.startsWith('zh')?zh:en
const rows=ref<any[]>([]), total=ref(0), error=ref(''), warning=ref(''), loading=ref(false)
// A load that failed for a transient reason (network, timeout, server) is retried once the page's own refresh recovers.
let revision=0, transientFailure=false
async function load(){const current=++revision;loading.value=true;error.value='';try{
  if(props.candidateSetId && props.sessionId){const {data}=await getAgentCandidateSet(props.sessionId,props.candidateSetId,{limit:4,offset:0});if(current!==revision)return;rows.value=data.rows.slice(0,4);total.value=data.summary.selected_count}
  else if(props.postprocessing){const {data}=await request.post(`/api/v1/jobs/${props.jobId}/postprocessing/results`,{limit:4,offset:0});if(current!==revision)return;rows.value=data.rows;total.value=data.total}
  else {const result=await listBackendJobResults(props.jobId,{limit:4,offset:0});if(current!==revision)return;rows.value=result.data;total.value=Number(result.headers['x-total-count']||result.data.length)}
  const {data:job}=await getBackendJob(props.jobId,{summary:true});if(current!==revision)return;const output=job.tasks[0]?.output_payload||{};warning.value=output.warning||output.quantity_warning||''
}catch(e:any){if(current===revision){error.value=displayErrorMessage(e);transientFailure=['network','timeout','server'].includes(requestErrorKind(e)||'')}}finally{if(current===revision)loading.value=false}}
watch(()=>[props.jobId,props.candidateSetId],load,{immediate:true});watch(()=>props.recovery,()=>{if(error.value&&transientFailure&&!loading.value)void load()});onBeforeUnmount(()=>{revision++})
</script>
