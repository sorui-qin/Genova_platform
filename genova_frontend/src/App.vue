<script setup lang="ts">
import Loading from '@/components/Loading/index.vue'
import Toaster from '@/components/ui/toast/Toaster.vue'
import { Toaster as SonnerToaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { defineAsyncComponent } from 'vue'

const VueQueryDevtools = import.meta.env.DEV && import.meta.env.VITE_DEVTOOLS === 'true'
  ? defineAsyncComponent(() => import('@tanstack/vue-query-devtools').then(module => module.VueQueryDevtools))
  : null
</script>

<template>
  <TooltipProvider>
    <Toaster />
    <SonnerToaster />
    <VueQueryDevtools v-if="VueQueryDevtools" />

    <Suspense>
      <router-view v-slot="{ Component }">
        <component :is="Component" />
      </router-view>

      <template #fallback>
        <Loading />
      </template>
    </Suspense>
  </TooltipProvider>
</template>
