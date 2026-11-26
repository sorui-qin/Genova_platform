<template>
  <footer class="border-t border-slate-200 bg-white">
    <div class="mx-auto max-w-6xl px-6 py-14">
      <div class="grid gap-10 sm:grid-cols-2 lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
        <div>
          <div class="mb-5 flex items-center gap-2.5">
            <img
              :src="genovaLogo"
              alt="Genova"
              class="h-9 w-auto object-contain"
            />
          </div>
          <p class="max-w-sm text-sm leading-6 text-slate-500">
            {{ $t('platform.footerDescription') }}
          </p>
        </div>

        <div>
          <div class="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">{{ $t('platform.workflows') }}</div>
          <div class="space-y-2.5">
            <button class="block text-sm text-slate-600 transition hover:text-blue-600" @click="go('/molgen')">{{ $t('platform.deNovoGeneration') }}</button>
            <button class="block text-sm text-slate-600 transition hover:text-blue-600" @click="go('/molopt')">{{ $t('platform.leadOptimization') }}</button>
          </div>
        </div>

        <div>
          <div class="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">{{ $t('platform.platform') }}</div>
          <div class="space-y-2.5">
            <button class="block text-sm text-slate-600 transition hover:text-blue-600" @click="go('/protein-preparation')">{{ $t('platform.proteinPreparation') }}</button>
            <button class="block text-sm text-slate-600 transition hover:text-blue-600" @click="go('/dashboard')">{{ $t('platform.dashboard') }}</button>
            <button class="block text-sm text-slate-600 transition hover:text-blue-600" @click="go('/datacenter')">{{ $t('platform.dataCenter') }}</button>
          </div>
        </div>

        <div>
          <div class="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">{{ $t('platform.contact') }}</div>
          <div class="text-sm text-slate-600">
            <a class="transition hover:text-blue-600" href="mailto:ruiqin2001@zju.edu.cn">ruiqin2001@zju.edu.cn</a>
          </div>
        </div>
      </div>
    </div>
  </footer>
</template>

<script setup lang="ts">
const genovaLogo = `${import.meta.env.BASE_URL}genova-logo.svg`

import { useRouter } from 'vue-router'

const router = useRouter()
function go(path: string) {
  router.push(path)
}
</script>
