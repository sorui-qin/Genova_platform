<template>
  <index_header />

  <main class="bg-white text-slate-900">
    <!-- Hero -->
    <section id="overview" class="px-6 pb-20 pt-28">
      <div class="mx-auto max-w-6xl">
        <p class="mb-4 text-sm font-medium uppercase tracking-widest text-blue-600">
          {{ $t('platform.homeEyebrow') }}
        </p>
        <h1 class="max-w-3xl text-4xl font-bold leading-[1.15] tracking-tight text-slate-900 sm:text-5xl">
          {{ $t('platform.homeTitle') }}
        </h1>
        <p class="mt-5 max-w-2xl text-lg leading-relaxed text-slate-500">
          {{ $t('platform.homeDescription') }}
        </p>
        <div class="mt-8 flex flex-wrap gap-3">
          <Button variant="outline" class="h-10 rounded-none px-5" @click="router.push('/agent')">{{ $t('platform.homeAssistant') }}</Button>
          <Button
            class="h-10 rounded-none bg-blue-600 px-5 text-sm font-medium text-white hover:bg-blue-700"
            @click="router.push('/dashboard')"
          >
            {{ $t('platform.dashboard') }}
            <ArrowRight class="ml-2 h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            class="h-10 rounded-none border-slate-300 px-5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            @click="scrollTo('modules')"
          >
            {{ $t('platform.exploreModules') }}
          </Button>
        </div>
      </div>
    </section>

    <!-- Modules -->
    <section id="modules" class="border-t border-slate-200 bg-slate-50 px-6 py-20">
      <div class="mx-auto max-w-6xl">
        <p class="mb-2 text-sm font-medium uppercase tracking-widest text-blue-600">{{ $t('platform.modules') }}</p>
        <h2 class="text-2xl font-bold tracking-tight sm:text-3xl">{{ $t('platform.chooseWorkflow') }}</h2>

        <div class="mt-10 grid gap-4 md:grid-cols-2">
          <button
            v-for="card in moduleCards"
            :key="card.title"
            class="group border border-slate-200 bg-white p-6 text-left transition hover:border-blue-200 hover:shadow-sm"
            @click="router.push(card.route)"
          >
            <div class="mb-4 flex h-9 w-9 items-center justify-center border border-slate-200 bg-white">
              <component :is="card.icon" class="h-4 w-4 text-slate-700" />
            </div>
            <div class="text-base font-semibold text-slate-900">{{ card.title }}</div>
            <div class="mt-1 text-sm leading-relaxed text-slate-500">{{ card.description }}</div>
            <div class="mt-4 flex flex-wrap gap-1.5">
              <span
                v-for="chip in card.chips"
                :key="chip"
                class="bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500"
              >
                {{ chip }}
              </span>
            </div>
            <div class="mt-4 inline-flex items-center gap-1 text-xs font-medium text-blue-600 opacity-0 transition group-hover:opacity-100">
              {{ $t('platform.openModule') }}
              <ArrowRight class="h-3 w-3" />
            </div>
          </button>
        </div>
      </div>
    </section>

    <!-- Workflow -->
    <section id="workflows" class="border-t border-slate-200 bg-slate-50 px-6 py-20">
      <div class="mx-auto max-w-6xl">
        <p class="mb-2 text-sm font-medium uppercase tracking-widest text-blue-600">{{ $t('platform.howItWorks') }}</p>
        <h2 class="text-2xl font-bold tracking-tight sm:text-3xl">{{ $t('platform.twoWorkflows') }}</h2>

        <div class="mt-10 grid gap-px border border-slate-200 bg-slate-200 md:grid-cols-4">
          <div
            v-for="step in workflowSteps"
            :key="step.code"
            class="bg-white p-8"
          >
            <div class="text-sm font-bold text-blue-600">{{ step.code }}</div>
            <h3 class="mt-4 text-lg font-semibold text-slate-900">{{ step.title }}</h3>
            <p class="mt-2 text-sm leading-relaxed text-slate-500">{{ step.description }}</p>
          </div>
        </div>
      </div>
    </section>

    <!-- CTA -->
    <section class="border-t border-slate-200 bg-slate-50 px-6 py-20">
      <div class="mx-auto max-w-2xl text-center">
        <h2 class="text-2xl font-bold tracking-tight sm:text-3xl">{{ $t('platform.startWorkflow') }}</h2>
        <div class="mt-8 flex justify-center gap-3">
          <Button
            class="h-10 rounded-none bg-blue-600 px-5 text-sm font-medium text-white hover:bg-blue-700"
            @click="router.push('/dashboard')"
          >
            {{ $t('platform.dashboard') }}
            <ArrowRight class="ml-2 h-4 w-4" />
          </Button>
        </div>
      </div>
    </section>
  </main>

  <index_footer />
</template>

<script setup lang="ts">
import { translate } from '@/i18n'
import { computed } from 'vue'

import { useRouter } from 'vue-router'
import {
  ArrowRight,
  FlaskConical,
  Funnel,
  Sparkles,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import AlphaHelixIcon from '@/components/Layout/AlphaHelixIcon.vue'
import index_header from '@/pages/home/components/Header.vue'
import index_footer from '@/pages/home/components/Footer.vue'

const router = useRouter()

const moduleCards = computed(() => [
  {
    title: translate('platform.proteinPreparation'),
    description: translate('platform.homePrepareCard'),
    route: '/protein-preparation',
    icon: AlphaHelixIcon,
    chips: [translate('platform.proteinGuided'), translate('platform.sharedContext')],
  },
  {
    title: translate('platform.deNovoGeneration'),
    description: translate('platform.surfgenCard'),
    route: '/molgen',
    icon: Sparkles,
    chips: ['SurfGen', 'ECloudGen', 'SDF / CSV'],
  },
  {
    title: translate('platform.leadOptimization'),
    description: translate('platform.homeOptimizeCard'),
    route: '/molopt',
    icon: FlaskConical,
    chips: ['DELETE', 'EPSO'],
  },
  {
    title: translate('platform.postprocessing'),
    description: translate('platform.postprocessingDescription'),
    route: '/postprocessing',
    icon: Funnel,
    chips: ['TarPass', 'CSV / SDF'],
  },
])

const workflowSteps = computed(() => [
  {
    code: '01',
    title: translate('platform.prepareContext'),
    description: translate('platform.homePrepareCard'),
  },
  {
    code: '02',
    title: translate('platform.chooseModel'),
    description: translate('platform.homeModelStep'),
  },
  {
    code: '03',
    title: translate('platform.reviewResults'),
    description: translate('platform.resultsStep'),
  },
  { code: '04', title: translate('platform.postprocessing'), description: translate('platform.postprocessStep') },
])

function scrollTo(id: string) {
  const el = document.getElementById(id)
  if (!el) return
  const top = el.getBoundingClientRect().top + window.scrollY - 80
  window.scrollTo({ top, behavior: 'smooth' })
}
</script>

<style scoped>
section {
  scroll-margin-top: 80px;
}
</style>

<route lang="yaml">
meta:
  layout: blank
</route>
