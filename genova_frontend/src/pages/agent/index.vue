<template>
  <AppFrame :task="null">
    <div class="flex h-full min-h-0 flex-col overflow-hidden bg-slate-50">
      <PageHeader :title="translate('agent.title')" :help="{ path: '/help', query: { article: 'assistant-workflow' } }" :help-label="translate('platform.operationGuide')">
          <Dialog>
            <DialogTrigger as-child>
              <Button type="button" variant="outline" class="gap-2">
                <Settings2 class="h-4 w-4" aria-hidden="true" />
                {{ translate('settings.agent_api') }}
              </Button>
            </DialogTrigger>
            <DialogContent class="max-h-[85vh] overflow-y-auto sm:max-w-xl" :aria-describedby="undefined">
              <DialogTitle class="sr-only">{{ translate('settings.agent_api') }}</DialogTitle>
              <AgentApiSettings />
            </DialogContent>
          </Dialog>
      </PageHeader>
      <AgentSessionPanel v-if="agentIdentity" :key="agentIdentity" />
    </div>
  </AppFrame>
</template>
<script setup lang="ts">
import PageHeader from '@/components/workbench/PageHeader.vue'
import { Settings2 } from 'lucide-vue-next'
import { translate } from '@/i18n'
import AppFrame from '@/components/Layout/appFrame.vue'
import AgentSessionPanel from './components/AgentSessionPanel.vue'
import { useAgentIdentity } from '@/composables/useAgentIdentity'
const agentIdentity = useAgentIdentity()
import AgentApiSettings from '@/pages/settings/components/AgentApiSettings.vue'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
</script>
<route lang="yaml">
meta:
  layout: blank
</route>
