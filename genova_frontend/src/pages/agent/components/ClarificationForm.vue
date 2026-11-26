<template>
        <form class="space-y-4 rounded-xl border border-amber-200 bg-amber-50/70 p-4 sm:p-5" @submit.prevent="$emit('submit')">
          <div class="flex items-start gap-3"><MessageSquareText class="mt-0.5 h-5 w-5 shrink-0 text-amber-700" aria-hidden="true" /><div><h3 class="font-semibold text-slate-800">{{ t('agent.session.completeInformation') }}</h3><p class="mt-1 text-sm text-amber-900">{{ t('agent.session.completeInformationHint') }}</p></div></div>
          <fieldset class="space-y-4" :disabled="busy || turnRunning || pendingRequest">
            <div v-for="(requirement, index) in requirements" :key="requirement" class="space-y-2">
              <label :for="`requirement-${index}`" class="block break-words text-sm font-medium text-slate-700">{{ kind(requirement) === 'engine' ? t('agent.session.model') : kind(requirement) === 'count' ? t('agent.session.generationCount') : requirement }}</label>
              <template v-if="kind(requirement) === 'engine' || kind(requirement) === 'confirmation'">
                <select :id="`requirement-${index}`" v-model="answers[requirement]" class="w-full rounded-lg border bg-white p-2.5" required><option :value="undefined" disabled>{{ t('agent.ui.choose') }}</option><template v-if="clarificationField(requirement)?.type === 'engine'"><option v-for="(capability, key) in generators" :key="key" :value="key" :disabled="!capability.enabled">{{ key }}{{ !capability.enabled ? ' · ' + t('agent.ui.enabledReason') : '' }}</option></template><template v-else><option v-for="choice in confirmationChoices(requirement)" :key="choice" :value="t(choice)">{{ t(choice) }}</option></template></select>
                <p v-if="clarificationField(requirement)?.id === 'preparation_defaults'" class="text-xs text-slate-500">{{ t('agent.ui.defaultsScope') }}</p>
              </template>
              <template v-else-if="kind(requirement) === 'delete'">
                <p v-if="confirmedDeleteEdit" class="break-all text-xs text-emerald-800">{{ t('agent.session.confirmedEdit', { mode: confirmedDeleteEdit.mode }) }} · {{ confirmedDeleteEdit.id }}</p>
                <p v-else class="text-xs text-amber-800">{{ t('agent.session.editRequired') }}</p>
                <Button :id="`requirement-${index}`" type="button" variant="outline" :disabled="!contextReady" @click="$emit('openDelete')">{{ t('agent.session.deleteVisualEdit') }} <ArrowUpRight class="ml-1 h-4 w-4" aria-hidden="true" /></Button>
              </template>

              <template v-else-if="kind(requirement) === 'count'"><input :id="`requirement-${index}`" v-model="answers[requirement]" type="number" min="1" max="50000" step="1" required :aria-describedby="`requirement-hint-${index}`" class="w-full rounded-lg border border-amber-200 bg-white p-2.5 sm:max-w-48" :placeholder="t('agent.session.countPlaceholder')" /><p :id="`requirement-hint-${index}`" class="text-xs text-slate-500">{{ t('agent.session.countPlaceholder') }}</p></template>
              <textarea v-else :id="`requirement-${index}`" v-model="answers[requirement]" required maxlength="1000" class="min-h-20 w-full rounded-lg border border-amber-200 bg-white p-2.5" :placeholder="t('agent.session.answerPlaceholder')" />
            </div>
            <Button type="submit" :disabled="!canSubmitClarification">{{ t('agent.session.submitInformation') }}</Button>
          </fieldset>
        </form>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { MessageSquareText, ArrowUpRight } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { requirementKind, type ClarificationField } from './sessionPresentation'
const props = defineProps<{requirements:string[]; fields?:ClarificationField[]; generators:Record<string,any>; busy:boolean;turnRunning:boolean;pendingRequest:boolean;canSubmitClarification:boolean;contextReady:boolean;confirmedDeleteEdit?:{id:string;mode:string}}>()
const answers = defineModel<Record<string,string|number>>('answers',{required:true})
defineEmits<{submit:[];openDelete:[]}>()
const {t}=useI18n()
const kind = (requirement:string) => requirementKind(requirement, props.fields)
const clarificationField = (requirement:string) => props.fields?.find(field=>field.requirement===requirement)
const confirmationChoices = (requirement:string) => clarificationField(requirement)?.id === 'preparation_defaults' ? ['agent.ui.defaultsYes','agent.ui.defaultsNo'] : ['agent.ui.yes','agent.ui.no']
</script>
