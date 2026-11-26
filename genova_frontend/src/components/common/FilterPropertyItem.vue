<template>
  <div class="border rounded-lg p-4 space-y-4 bg-white" :class="{ 'bg-gray-50': index % 2 === 1 }">
    <!-- Property Selector -->
    <div class="grid grid-cols-1 md:grid-cols-8 gap-4 items-center">
      <div class="space-y-2 md:col-span-2">
        <Label class="text-sm font-medium">{{ t('result.SelectProps') }}</Label>
        <Select 
          v-if="!needCascade"
          :model-value="item.selectedValue"
          @update:model-value="(value) => $emit('propertyChange', value)"
        >
          <SelectTrigger>
            <SelectValue :placeholder="t('result.SelectProps')" />
          </SelectTrigger>
          <SelectContent class="z-[200]">
            <SelectItem 
              v-for="option in availableOptions"
              :key="option.value"
              :value="option.value"
              :disabled="option.disabled"
            >
              {{ option.label }}
            </SelectItem>
          </SelectContent>
        </Select>
        <!-- Cascader for nested options would need custom implementation -->
      </div>

      <!-- Chart Container -->
      <div class="md:col-span-5 space-y-1">
        <!-- Chart -->
        <div class="relative">
          <div 
            :id="`chart-${item.key}`"
            class="w-full h-[70px] bg-gray-100 rounded border"
          ></div>
        </div>

        <!-- Min/Max Values Display with Input Controls -->
        <div class="flex items-center justify-between gap-2 text-xs text-gray-500 px-1">
          <div class="flex items-center gap-1">
            <span>Min:</span>
            <Input
              :model-value="item.minV"
              @update:model-value="(value) => $emit('updateMin', value)"
              placeholder="Min"
              class="text-xs h-6 w-24 px-1"
            />
          </div>
          <div class="flex items-center gap-1">
            <span>Max:</span>
            <Input
              :model-value="item.maxV"
              @update:model-value="(value) => $emit('updateMax', value)"
              placeholder="Max"
              class="text-xs h-6 w-24 px-1"
            />
          </div>
        </div>

        <!-- Range Slider -->
        <div class="px-2">
          <RangeSlider
            :model-value="[item.minV, item.maxV]"
            :min="dataMin"
            :max="dataMax"
            :step="0.001"
            @update:model-value="(value) => $emit('updateRange', value)"
          />
        </div>
      </div>

      <!-- Delete Button -->
      <div class="flex items-center justify-center">
        <Button
          variant="outline"
          size="icon"
          :disabled="!canDelete"
          @click="$emit('delete')"
          class="h-8 w-8 rounded-full text-red-600 hover:text-red-700 hover:bg-red-50"
        >
          <Trash2 class="h-4 w-4" />
        </Button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Trash2 } from 'lucide-vue-next'

// UI Components
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { RangeSlider } from '@/components/ui/range-slider'

interface FilterItem {
  key: string
  num: number
  selected?: string[]
  selectedValue?: string
  range: [number, number]
  offset: number
  scale: number
  minV: number
  maxV: number
}

interface OptionItem {
  label: string
  value: string
  disabled?: boolean
}

interface Props {
  item: FilterItem
  index: number
  availableOptions: OptionItem[]
  needCascade: boolean
  canDelete: boolean
  dataMin: number
  dataMax: number
}

defineProps<Props>()

defineEmits<{
  propertyChange: [value: string]
  updateMin: [value: string | number]
  updateMax: [value: string | number]
  updateRange: [value: [number, number]]
  delete: []
}>()

const { t } = useI18n()
</script> 