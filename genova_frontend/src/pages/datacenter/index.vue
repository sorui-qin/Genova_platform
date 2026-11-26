<template>
  <app_frame>
    <div class="bg-gray-50/30">
      <PageHeader :title="t('platform.dataCenter')" :help="{ path: '/help', query: { article: 'datasets-workflow' } }" :help-label="t('platform.operationGuide')" />

      <!-- Main Content -->
      <div class="flex-1 max-w-[1680px] mx-auto px-6 min-h-0 overflow-hidden">
        <div class="w-full h-full min-h-0 flex flex-col">
          <!-- Tab Navigation -->
          <div class="flex flex-wrap gap-1.5 border-b border-gray-200 pb-2 mb-4">
            <Button
              v-for="tab in tabs"
              :key="tab.value"
              :variant="activeTab === tab.value ? 'default' : 'ghost'"
              size="sm"
              class="text-xs h-8"
              :disabled="tab.disabled"
              @click="updateTabUrl(tab.value)"
            >
              <component :is="tab.icon" class="w-3 h-3 mr-1.5" />
              {{ t(tab.label) }}
            </Button>
          </div>

          <!-- Tab Contents -->
          <div class="flex-1 min-h-0">
            <!-- Built-in Datasets Tab -->
            <div v-if="activeTab === 'builtin'" class="h-full">
  
              <Card class="p-4 bg-white shadow-none">
                <div class="flex items-center justify-between mb-4">
                  <h2 class="text-lg font-semibold text-gray-900 flex items-center">
                    <Database class="w-5 h-5 mr-2 text-violet-600" />
                    {{ t('data.内置数据库') }}
                  </h2>
                  <ResourceSort v-model="builtinSort" /><Badge variant="secondary">{{ builtinLoaded ? builtinDatasets.length : '—' }} {{ t('data.个数据库') }}</Badge>
                </div>

                <div v-if="builtinError" role="alert" class="mb-3 flex items-center justify-between gap-3 text-sm text-red-700">
                  <span>{{ builtinError }}</span>
                  <Button size="sm" variant="outline" :disabled="builtinRefreshing" @click="loadBuiltinDatasets()">{{ $t('platform.retryLoad') }}</Button>
                </div>
                <p v-if="builtinRefreshing" role="status" class="text-sm text-slate-500">{{ $t(builtinLoaded ? 'platform.refreshing' : 'platform.loading') }}</p>
                <div v-if="builtinRefreshing && !builtinLoaded" class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                  <Skeleton v-for="n in 4" :key="n" class="h-32 w-full" />
                </div>
                <p v-if="builtinLoaded && !builtinDatasets.length" class="text-sm text-slate-500">{{ t('data.数据中心为空') }}</p>
                <div v-if="builtinLoaded" class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                  <div
                    v-for="dataset in sortedBuiltinDatasets"
                    :key="dataset.dataset_id"
                    class="bg-gray-50 border border-gray-200 rounded-lg p-4 cursor-pointer hover:shadow-md hover:border-violet-300"
                    @click="openDataPreview(dataset)"
                  >
                    <h3 class="font-semibold text-gray-900">{{ dataset.name }}</h3>
                    <p class="mt-1 text-sm text-gray-500">{{ dataset.description }}</p>
                    <div class="mt-3 flex items-center justify-between text-xs text-gray-500">
                      <Badge variant="outline">{{ getFileExtension(dataset.name).toUpperCase() }}</Badge>
                      <span>{{ formatFileSize(dataset.file_size) }}</span>
                    </div>
                  </div>
                </div>
              </Card>
            </div>

            <!-- My Data Tab -->
            <div v-else-if="activeTab === 'mydata'" class="h-full">
              <Card class="p-4 h-full flex flex-col bg-white shadow-none">
              <!-- Header with Workspace Switcher -->
              <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div class="flex items-center space-x-4">
                  <h2 class="text-lg font-semibold text-gray-900">
                    {{ t('data.我的数据') }}
                  </h2>
                  <Badge variant="secondary">{{ dataLoaded ? filteredDataList.length : '—' }} {{ t('data.个文件') }}</Badge>
                  <span v-if="dataLoaded && isRefreshing" role="status" class="text-xs text-slate-500">{{ $t('platform.refreshing') }}</span>
                </div>
                <div class="flex items-center space-x-3">
                  <!-- View Mode Toggle -->
                  <div class="flex items-center space-x-1 border rounded-md">
                    <Button
                      :variant="viewMode === 'grid' ? 'default' : 'ghost'"
                      size="sm"
                      class="h-8 px-2"
                      :aria-label="t('data.网格视图')"
                      :aria-pressed="viewMode === 'grid'"
                      @click="viewMode = 'grid'"
                    >
                      <LayoutGrid class="w-4 h-4" />
                    </Button>
                    <Button
                      :variant="viewMode === 'list' ? 'default' : 'ghost'"
                      size="sm"
                      class="h-8 px-2"
                      :aria-label="t('data.列表视图')"
                      :aria-pressed="viewMode === 'list'"
                      @click="viewMode = 'list'"
                    >
                      <List class="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              </div>

              <div class="mb-4 flex flex-wrap gap-2" role="group" :aria-label="t('platform.resourceCategories')">
                <Button v-for="category in resourceCategories" :key="category.value" size="sm" :variant="resourceCategory === category.value ? 'secondary' : 'ghost'" :aria-pressed="resourceCategory === category.value" class="gap-2" @click="resourceCategory = category.value">
                  <component :is="category.icon" class="size-4" />{{ t(category.label) }}
                  <span class="rounded-full bg-slate-100 px-1.5 text-xs tabular-nums text-slate-500">{{ dataLoaded ? categoryCounts[category.value] : '—' }}</span>
                </Button>
              </div>

              <!-- Search and Filter with Upload and Actions -->
              <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div class="flex w-full min-w-0 flex-wrap items-center gap-2 md:w-auto md:flex-1">
                  <div class="relative min-w-0 flex-1 sm:max-w-72">
                    <Search class="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
                    <Input
                      v-model="searchQuery"
                      :placeholder="t('data.搜索文件名')"
                      class="w-full pl-10"
                    />
                  </div>
                  <Select v-model="fileTypeFilter">
                    <SelectTrigger class="w-32">
                      <SelectValue :placeholder="t('data.文件类型')" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">{{ t('data.全部') }}</SelectItem>
                      <SelectItem v-if="['all', 'other'].includes(resourceCategory)" value="csv">CSV/TSV</SelectItem>
                      <SelectItem v-if="['all', 'raw'].includes(resourceCategory)" value="pdb">PDB</SelectItem>
                      <SelectItem v-if="['all', 'raw'].includes(resourceCategory)" value="cif">CIF</SelectItem>
                      <SelectItem v-if="['all', 'ligand'].includes(resourceCategory)" value="sdf">SDF</SelectItem>
                      <SelectItem v-if="['all', 'ligand'].includes(resourceCategory)" value="mol">MOL</SelectItem>
                      <SelectItem v-if="['all', 'ligand'].includes(resourceCategory)" value="mol2">MOL2</SelectItem>
                      <SelectItem v-if="['all', 'prepared'].includes(resourceCategory)" value="prepared_receptor">{{ $t('platform.preparedReceptor') }}</SelectItem>
                      <SelectItem v-if="['all', 'prepared'].includes(resourceCategory)" value="protein_context">{{ $t('platform.proteinContextLabel') }}</SelectItem>
                    </SelectContent>
                  </Select>
                  <ResourceSort v-model="resourceSort" />
                </div>
                <div class="flex w-full flex-wrap items-center gap-2 md:w-auto">
                  <Button 
                    @click="showUploadDialog = true" 
                    size="sm"
                    class="flex items-center"
                  >
                    <Plus class="w-4 h-4 mr-2" />
                    {{ t('data.上传文件') }}
                  </Button>
                  <Button 
                    variant="destructive" 
                    size="sm"
                    :disabled="selectedItems.length === 0"
                    @click="confirmBatchDelete"
                  >
                    <Trash2 class="w-4 h-4 mr-2" />
                    {{ t('data.批量删除') }} ({{ selectedItems.length }})
                  </Button>
                </div>
              </div>

              <!-- Content Area with ScrollArea -->
              <div v-if="dataError" role="alert" class="mb-3 flex items-center justify-between gap-3 text-sm text-red-700">
                <span>{{ dataError }}</span>
                <Button size="sm" variant="outline" :disabled="isRefreshing" @click="loadDataList()">{{ $t('platform.retryLoad') }}</Button>
              </div>
              <div class="flex-1 overflow-hidden">
                <!-- Loading State - Skeleton -->
                <div v-if="isLoading" class="space-y-4 pr-4">
                  <!-- Grid view skeleton -->
                  <div v-if="viewMode === 'grid'" class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 min-[1800px]:grid-cols-4 gap-4">
                    <div v-for="n in 12" :key="n" class="bg-white border rounded-lg p-4">
                      <div class="flex items-center justify-between mb-3">
                        <Skeleton class="h-4 w-4 rounded" />
                        <Skeleton class="h-8 w-8 rounded" />
                      </div>
                      <div class="space-y-2">
                        <Skeleton class="h-4 w-3/4" />
                        <Skeleton class="h-3 w-1/2" />
                        <Skeleton class="h-3 w-2/3" />
                      </div>
                    </div>
                  </div>
                  <!-- List view skeleton -->
                  <div v-else class="space-y-2">
                    <div v-for="n in 12" :key="n" class="flex items-center p-3 bg-white border rounded-lg">
                      <Skeleton class="h-4 w-4 rounded mr-3" />
                      <Skeleton class="h-8 w-8 rounded mr-4" />
                      <div class="flex-1 space-y-2">
                        <Skeleton class="h-4 w-1/3" />
                        <Skeleton class="h-3 w-1/2" />
                      </div>
                      <div class="flex space-x-2">
                        <Skeleton class="h-8 w-8 rounded" />
                        <Skeleton class="h-8 w-8 rounded" />
                        <Skeleton class="h-8 w-8 rounded" />
                      </div>
                    </div>
                  </div>
                </div>

                <!-- Empty State -->
                <div v-else-if="dataLoaded && filteredDataList.length === 0" class="flex items-center justify-center h-full">
                  <div class="text-center">
                    <Database class="w-12 h-12 mx-auto mb-4 text-gray-400" />
                    <h3 class="text-lg font-medium text-gray-900 mb-2">
                      {{ dataList.length ? $t('platform.noMatchingFiles') : t('data.您还未产生任何个人数据') }}
                    </h3>
                    <p v-if="!dataList.length" class="text-sm text-gray-500 mb-4">
                      {{ t('data.请上传数据文件开始使用') }}
                    </p>
                    <Button v-if="!dataList.length" @click="showUploadDialog = true">
                      <Plus class="w-4 h-4 mr-2" />
                      {{ t('data.上传新数据') }}
                    </Button>
                  </div>
                </div>

                <!-- Data Content with ScrollArea -->
                <ScrollArea v-else-if="dataLoaded" class="h-full">
                  <!-- Data Grid View -->
                  <div v-if="viewMode === 'grid'" class="pr-4 space-y-6">
                    <div v-for="group in groupedDataList" :key="group.label">
                      <!-- Group Header -->
                      <div class="mb-3">
                        <h3 class="text-sm font-semibold text-gray-500 flex items-center">
                          {{ t(group.label) }}
                          <Badge variant="secondary" class="ml-2 text-xs text-gray-500">{{ group.items.length }}</Badge>
                        </h3>
                        <div class="h-px bg-gray-200 mt-2"></div>
                      </div>
                      
                      <!-- Group Items -->
                      <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 min-[1800px]:grid-cols-4 gap-4">
                        <div
                          v-for="item in group.items"
                          :key="item.dataset_id"
                          class="group relative bg-white border rounded-lg p-4 hover:shadow-md transition-all duration-200 cursor-pointer"
                          @click="openDataPreview(item)"
                        >
                          <!-- Selection Checkbox -->
                          <div class="absolute top-2 left-2 z-10">
                            <Checkbox
                              :checked="selectedItems.includes(item.dataset_id)"
                              @update:checked="toggleSelection(item.dataset_id, $event)"
                              @click.stop
                            />
                          </div>

                          <!-- File Name and Icon - 同一排 -->
                          <div class="flex items-center justify-between mb-3 pt-2">
                            <div class="flex-1 min-w-0 mr-3">
                              <Tooltip :delay-duration="100">
                                <TooltipTrigger asChild>
                                  <div class="text-lg font-bold text-gray-900 truncate leading-tight cursor-default">
                                    {{ ['protein_context', 'prepared_receptor'].includes(item.kind) ? item.name : getBaseName(item.name) }}
                                  </div>
                                </TooltipTrigger>
                                <TooltipContent>
                                  <p>{{ item.name }}</p>
                                </TooltipContent>
                              </Tooltip>
                            </div>
                            <div class="relative flex-shrink-0">
                              <component 
                                :is="item.kind === 'protein_context' ? Database : getFileIcon(item.file_name || item.name)"
                                class="w-10 h-10"
                                :class="getFileIconColor(item.file_name || item.name)"
                              />
                              <Badge 
                                :class="getFileTypeBadgeClass(getFileExtension(item.file_name || item.name))"
                                class="absolute -bottom-1 -right-1 text-xs px-1"
                              >
                                {{ item.kind === 'protein_context' ? 'CONTEXT' : getFileExtension(item.file_name || item.name).toUpperCase() }}
                              </Badge>
                            </div>
                          </div>

                          <select v-if="item.kind !== 'protein_context' && item.files?.length > 1" class="mt-2 w-full min-w-0 rounded border bg-white p-1 text-xs" :value="item.file_id" :aria-label="$t('platform.datasetFile')" @click.stop @change="selectDatasetFile(item, ($event.target as HTMLSelectElement).value)">
                              <option v-for="file in item.files" :key="file.id" :value="file.id">{{ file.file_role === 'prepared_complex' ? $t('platform.preparedComplex') : file.file_role === 'context_receptor' ? $t('platform.apoReceptor') : file.original_filename }}</option>
                            </select>

                          <!-- File Info -->
                          <div class="space-y-2">
                            <div class="text-xs text-gray-500 space-y-1">
                              <template v-if="item.kind === 'protein_context'">
                                <div>{{ $t('platform.statusLabel') }} {{ statusLabel(item.status) }}</div>
                                <div v-for="(value, label) in contextDetails(item)" :key="label">{{ label }} {{ value }}</div>
                              </template>
                              <div class="flex items-center">
                                <Calendar class="w-3 h-3 mr-1" />
                                {{ formatDate(item.created_at) }}
                              </div>
                              <div class="flex items-center" v-if="item.file_size">
                                <HardDrive class="w-3 h-3 mr-1" />
                                {{ formatFileSize(item.file_size) }}
                              </div>
                              <div class="flex items-center" v-if="item.source">
                                <FolderOpen class="w-3 h-3 mr-1" />
                                {{ getSourceDisplay(item.source) }}
                              </div>
                            </div>
                          </div>
                          <div v-if="item.kind === 'protein_context'" class="mt-3 flex gap-1">
                            <template v-if="['ready', 'succeeded'].includes(item.status)">
                              <Button size="sm" variant="outline" @click.stop="openContext(item, '/molgen')">{{ $t('platform.deNovoGeneration') }}</Button>
                              <Button size="sm" variant="outline" @click.stop="openContext(item, '/molopt')">{{ $t('platform.leadOptimization') }}</Button>
                            </template>
                            <Button v-else size="sm" variant="outline" @click.stop="editContext(item)">{{ $t('platform.prepare') }}</Button>
                          </div>

                          <!-- Actions (shown on hover) -->
                          <div class="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex space-x-1">
                            <Button
                              size="sm"
                              variant="outline"
                              class="h-7 w-7 p-0"
                              :aria-label="t('data.重命名文件')"
                              @click.stop="openRenameDialog(item)"
                            >
                              <Edit2 class="w-3 h-3" />
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              class="h-7 w-7 p-0"
                              :aria-label="t('data.下载')"
                              @click.stop="downloadFile(item)"
                            >
                              <Download class="w-3 h-3" />
                            </Button>
                            <Button
                              size="sm"
                              variant="destructive"
                              class="h-7 w-7 p-0"
                              :aria-label="t('platform.delete')"
                              @click.stop="confirmDeleteSingle(item)"
                            >
                              <Trash2 class="w-3 h-3" />
                            </Button>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <!-- Data List View -->
                  <div v-else class="pr-4 space-y-6">
                    <div v-for="group in groupedDataList" :key="group.label">
                      <!-- Group Header -->
                      <div class="mb-3">
                        <h3 class="text-sm font-semibold text-gray-500 flex items-center">
                          {{ t(group.label) }}
                          <Badge variant="secondary" class="ml-2 text-xs text-gray-500">{{ group.items.length }}</Badge>
                        </h3>
                        <div class="h-px bg-gray-200 mt-2"></div>
                      </div>
                      
                      <!-- Group Items -->
                      <div class="space-y-2">
                        <div
                          v-for="item in group.items"
                          :key="item.dataset_id"
                          class="group flex items-center p-3 bg-white border rounded-lg hover:shadow-sm transition-all duration-200"
                        >
                          <Checkbox
                            :checked="selectedItems.includes(item.dataset_id)"
                            @update:checked="toggleSelection(item.dataset_id, $event)"
                            class="mr-3"
                          />
                          
                          <div class="flex-1 min-w-0 cursor-pointer" @click="openDataPreview(item)">
                            <div class="flex items-center space-x-2">
                              <Tooltip :delay-duration="100">
                                <TooltipTrigger asChild>
                                  <p class="text-base font-bold text-gray-900 truncate">
                                    {{ ['protein_context', 'prepared_receptor'].includes(item.kind) ? item.name : getBaseName(item.name) }}
                                  </p>
                                </TooltipTrigger>
                                <TooltipContent>
                                  <p>{{ item.name }}</p>
                                </TooltipContent>
                              </Tooltip>
                              <Badge 
                                :class="getFileTypeBadgeClass(getFileExtension(item.file_name || item.name))"
                                class="text-xs"
                              >
                                {{ item.kind === 'protein_context' ? 'CONTEXT' : getFileExtension(item.file_name || item.name).toUpperCase() }}
                              </Badge>
                            </div>
                            <div class="flex items-center space-x-4 text-xs text-gray-500 mt-1">
                              <span v-if="item.kind === 'protein_context'" class="flex flex-wrap gap-x-3 gap-y-1">{{ statusLabel(item.status) }} <span v-for="(value, label) in contextDetails(item)" :key="label">{{ label }} {{ value }}</span></span>
                              <span class="flex items-center">
                                <Calendar class="w-3 h-3 mr-1" />
                                {{ formatDate(item.created_at) }}
                              </span>
                              <span v-if="item.file_size" class="flex items-center">
                                <HardDrive class="w-3 h-3 mr-1" />
                                {{ formatFileSize(item.file_size) }}
                              </span>
                              <span v-if="item.source" class="flex items-center">
                                <FolderOpen class="w-3 h-3 mr-1" />
                                {{ getSourceDisplay(item.source) }}
                              </span>
                            </div>
                            <select v-if="item.kind !== 'protein_context' && item.files?.length > 1" class="mt-2 w-full min-w-0 rounded border bg-white p-1 text-xs" :value="item.file_id" :aria-label="$t('platform.datasetFile')" @click.stop @change="selectDatasetFile(item, ($event.target as HTMLSelectElement).value)">
                              <option v-for="file in item.files" :key="file.id" :value="file.id">{{ file.file_role === 'prepared_complex' ? $t('platform.preparedComplex') : file.file_role === 'context_receptor' ? $t('platform.apoReceptor') : file.original_filename }}</option>
                            </select>
                          </div>

                          <div class="flex items-center space-x-2">
                            <template v-if="item.kind === 'protein_context' && isProteinContextReady({ ...item.meta, status: item.status })">
                              <Button size="sm" variant="ghost" @click="openContext(item, '/molgen')">{{ $t('platform.deNovoGeneration') }}</Button>
                              <Button size="sm" variant="ghost" @click="openContext(item, '/molopt')">{{ $t('platform.leadOptimization') }}</Button>
                            </template>
                            <Button v-else-if="item.kind === 'protein_context'" size="sm" variant="ghost" @click="editContext(item)">{{ $t('platform.prepare') }}</Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              :aria-label="t('data.重命名文件')"
                              @click="openRenameDialog(item)"
                            >
                              <Edit2 class="w-4 h-4" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              :aria-label="t('data.下载')"
                              @click="downloadFile(item)"
                            >
                              <Download class="w-4 h-4" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              :aria-label="t('platform.delete')"
                              @click="confirmDeleteSingle(item)"
                            >
                              <Trash2 class="w-4 h-4" />
                            </Button>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </ScrollArea>
              </div>
              </Card>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Upload Dialog -->
    <Dialog v-model:open="showUploadDialog">
      <DialogContent class="sm:max-w-md">
        <div class="space-y-4">
          <div class="text-center">
            <Upload class="w-12 h-12 mx-auto mb-4 text-gray-400" />
            <DialogTitle as="h3" class="text-lg font-semibold leading-7 tracking-normal">{{ t('data.上传文件') }}</DialogTitle>
            <DialogDescription class="text-sm text-gray-500">{{ t('data.支持PDB、CIF、CSV/TSV、SDF、MOL、MOL2格式') }}</DialogDescription>
          </div>
          
          <FileUploader
            accept=".pdb,.ent,.cif,.mmcif,.csv,.tsv,.txt,.sdf,.mol,.mol2"
            @upload-complete="handleUploadComplete"
            @upload-error="handleUploadError"
          />
        </div>
      </DialogContent>
    </Dialog>

    <!-- Data Preview Dialog -->
    <Dialog v-model:open="showPreviewDialog">
      <DialogContent class="max-w-7xl h-[85vh] flex flex-col">
        <DialogDescription class="sr-only">{{ t('platform.dialogA11y.preview') }}</DialogDescription>
        <div v-if="previewData.dataset_id" class="flex h-full min-h-0 flex-col">
          <div class="flex shrink-0 items-center justify-between mb-4 gap-3 pr-6">
            <DialogTitle as="h3" class="truncate text-lg font-semibold leading-7 tracking-normal">{{ previewData.name }}</DialogTitle>
            <div class="flex items-center space-x-2">
              <Button size="sm" variant="outline" @click="downloadFile(previewData)">
                <Download class="w-4 h-4 mr-2" />
                {{ t('result.下载') }}
              </Button>
            </div>
          </div>
          
          <dl v-if="previewData.contextDetails" class="mb-3 grid shrink-0 grid-cols-1 gap-x-6 gap-y-1 text-xs text-slate-600 sm:grid-cols-2"><div v-for="(value, label) in previewData.contextDetails" :key="label" class="flex gap-2"><dt>{{ label }}</dt><dd>{{ value }}</dd></div></dl>
          <details v-if="previewData.resourceFiles?.length" class="mb-3 shrink-0 rounded border p-2 text-sm">
            <summary class="cursor-pointer">{{ t('platform.resourceArtifacts') }}</summary>
            <div class="mt-2 grid max-h-40 gap-1 overflow-auto">
              <button v-for="file in previewData.resourceFiles" :key="file.id" class="flex items-center justify-between gap-3 rounded px-2 py-1 text-left hover:bg-slate-100" @click="downloadFile({ dataset_id: file.dataset_id, file_id: file.id, name: file.original_filename })">
                <span class="min-w-0 truncate">{{ artifactLabel(file) }}</span>
                <Download class="h-4 w-4 shrink-0" />
              </button>
            </div>
          </details>
          <div class="min-h-0 flex-1 overflow-hidden">
            <iframe
              v-if="isPdf(previewData.name)"
              :src="previewData.fileUrl"
              class="h-full w-full border-0"
            />
            
            <!-- PDB/CIF 结构预览器 -->
            <Protein3dMolstar 
              v-else-if="isStructure(previewData.name)" 
              ref="proteinViewerRef"
              :key="`${previewData.dataset_id}:${previewData.file_id}`"
              class="h-full"
              :wait_molstar_init="true"
            />
            
            <!-- 图片预览 -->
            <div v-else-if="isImage(previewData.name)" class="h-full flex items-center justify-center bg-gray-50">
              <img :src="previewData.fileUrl" class="max-h-full max-w-full object-contain" />
            </div>
            
            <div v-else-if="isDelimitedFile(previewData.name)" class="flex h-full min-h-0 flex-col gap-3 lg:flex-row">
              <div class="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
                <template v-if="!csvTable.error">
                  <ul v-if="csvTable.warnings.length" role="status" class="shrink-0 space-y-1 rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
                    <li v-for="(warning, index) in csvTable.warnings" :key="index">{{ tableIssueText(warning) }}</li>
                  </ul>
                  <div class="min-h-[120px] flex-1 overflow-auto border border-slate-200">
                    <table class="w-full text-sm">
                      <thead class="sticky top-0 bg-slate-50">
                        <tr>
                          <th v-if="csvSmilesColumn >= 0" class="px-3 py-2 text-left">{{ t('data_preview.structure') }}</th>
                          <th v-for="(header, column) in csvTable.headers" :key="column" class="whitespace-nowrap px-3 py-2 text-left">{{ header || t('platform.tableColumn', { number: column + 1 }) }}</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="(row, rowIndex) in csvPageRows" :key="(csvPage - 1) * 50 + rowIndex" class="border-t" :class="selectedCsvRow === (csvPage - 1) * 50 + rowIndex ? 'bg-blue-50' : ''">
                          <td v-if="csvSmilesColumn >= 0" class="px-3 py-2">
                            <Button size="sm" variant="outline" :disabled="!row[csvSmilesColumn]?.trim()"
                              :aria-label="t('platform.previewMoleculeRow', { row: (csvPage - 1) * 50 + rowIndex + 1 })"
                              @click="selectedCsvRow = (csvPage - 1) * 50 + rowIndex">{{ t('data_preview.show2dstructure') }}</Button>
                          </td>
                          <td v-for="(_, column) in csvTable.headers" :key="column" class="max-w-xs whitespace-pre-wrap break-words px-3 py-2">{{ row[column] ?? '' }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                  <div class="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
                    <span>{{ t('platform.tableRows', { count: csvTable.rows.length }) }}</span>
                    <div class="flex items-center gap-2">
                      <Button size="sm" variant="outline" :disabled="csvPage <= 1" @click="csvPage--">{{ t('data_preview.上一页') }}</Button>
                      <span>{{ t('platform.tablePage', { page: csvPage, pages: csvPages }) }}</span>
                      <Button size="sm" variant="outline" :disabled="csvPage >= csvPages" @click="csvPage++">{{ t('data_preview.下一页') }}</Button>
                    </div>
                  </div>
                </template>
                <template v-else>
                  <p role="alert" class="text-sm text-red-700">{{ csvTable.issue ? tableIssueText(csvTable.issue) : t('platform.tableParseFailed') }}</p>
                  <pre class="flex-1 overflow-auto whitespace-pre-wrap bg-slate-50 p-4 text-xs">{{ previewData.textContent }}</pre>
                </template>
              </div>
              <div v-if="selectedCsvInput" class="flex h-[min(40vh,360px)] min-h-[260px] flex-col gap-2 lg:h-auto lg:w-2/5 lg:min-w-[300px]">
                <Button size="sm" variant="outline" class="self-end" @click="selectedCsvRow = null">{{ t('platform.closeMoleculePreview') }}</Button>
                <MoleculePreview :input="selectedCsvInput" :caption="t('platform.previewMoleculeRow', { row: (selectedCsvRow ?? 0) + 1 })" class="min-h-0 flex-1" />
              </div>
            </div>

            <MoleculePreview
              v-else-if="previewData.moleculeInput"
              :input="previewData.moleculeInput"
            />
            
            <pre
              v-else-if="previewData.dataset_id && !isSpecialFile(previewData.name)"
              class="h-full overflow-auto whitespace-pre-wrap bg-slate-50 p-4 text-xs"
            >{{ previewData.textContent }}</pre>
            
            <!-- 不支持的文件类型 -->
            <div v-else class="h-full flex items-center justify-center bg-gray-50">
              <div class="text-center">
                <FileText class="w-12 h-12 mx-auto mb-4 text-gray-400" />
                <p class="text-sm text-gray-500">{{ t('data.预览不支持此文件类型') }}</p>
              </div>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>

    <!-- Rename Dialog -->
    <Dialog v-model:open="showRenameDialog">
      <DialogContent class="sm:max-w-md">
        <div class="space-y-4">
          <DialogTitle as="h3" class="text-lg font-semibold leading-7 tracking-normal">{{ t('data.重命名文件') }}</DialogTitle>
          <DialogDescription class="sr-only">{{ t('platform.dialogA11y.rename') }}</DialogDescription>
          <div class="space-y-2">
            <Label for="new-name">{{ t('data.新文件名') }}</Label>
            <div class="flex">
              <Input
                id="new-name"
                v-model="renameForm.newName"
                :maxlength="renameForm.fileId ? undefined : NAME_MAX_LENGTH"
                class="h-11 flex-1 py-1.5 font-mono text-base font-medium leading-normal"
              />
              <div v-if="renameForm.extension" class="flex items-center px-3">
                <div class="relative flex-shrink-0">
                  <component 
                    :is="getFileIcon(`dummy.${renameForm.extension}`)" 
                    class="w-10 h-10"
                    :class="getFileIconColor(`dummy.${renameForm.extension}`)"
                  />
                  <Badge 
                    :class="getFileTypeBadgeClass(renameForm.extension)"
                    class="absolute -bottom-1 -right-1 text-xs px-1"
                  >
                    {{ renameForm.extension.toUpperCase() }}
                  </Badge>
                </div>
              </div>
            </div>
            <p v-if="renameForm.fileId" class="text-xs" :class="renameNameTooLong ? 'text-rose-700' : 'text-slate-500'">
              {{ t('platform.uploadCheck.filenameBytes', { bytes: renameFilenameBytes, max: MAX_FILENAME_BYTES }) }}
            </p>
            <p v-else class="text-xs" :class="renameNameTooLong ? 'text-rose-700' : 'text-slate-500'">{{ nameLengthHint(renameForm.newName) }}</p>
          </div>
          <div class="flex justify-end space-x-2">
            <Button variant="outline" @click="showRenameDialog = false">
              {{ t('result.取消') }}
            </Button>
            <Button @click="confirmRename" :disabled="!renameForm.newName.trim() || renameNameTooLong">
              {{ t('result.确认') }}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>

    <!-- Delete Confirmation Dialog -->
    <AlertDialog v-model:open="showDeleteDialog">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {{ deleteTarget.type === 'single' ? t('data.确认删除') : t('data.确认批量删除') }}
          </AlertDialogTitle>
          <AlertDialogDescription>
            <template v-if="deleteTarget.type === 'single'">
              {{ t('data.确认删除文件') }} <span class="font-semibold">{{ deleteTarget.item?.name }}</span>{{ t('data.此操作不可撤销') }}
            </template>
            <template v-else>
              {{ t('data.确认删除选中的') }} <span class="font-semibold">{{ selectedItems.length }}</span> {{ t('data.个文件') }}{{ t('data.此操作不可撤销') }}
            </template>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{{ t('result.取消') }}</AlertDialogCancel>
          <AlertDialogAction :disabled="deleting" @click="handleDeleteConfirm" class="bg-destructive text-destructive-foreground hover:bg-destructive/90">
            <Loader2 v-if="deleting" class="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
            {{ t('result.确认删除') }}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

  </app_frame>
</template>

<script setup lang="ts">
import PageHeader from '@/components/workbench/PageHeader.vue'
import { getBackendDataset, listAllBackendDatasets, listBuiltinBackendDatasets, downloadBackendDataset } from '@/api/genovaBackend'
import { datacenterIdentity, queryClient } from '@/plugins/tanstack-vue-query'
import { isCancelledError } from '@tanstack/vue-query'
import { isProteinContextReady } from '@/types/proteinContext'
import i18n, { translate, statusLabel } from '@/i18n'
import { isNotFoundError, requestErrorMessage, displayErrorMessage } from '@/utils/requestError'
import { nonEmptyQueryValue, useQueryCleanup } from '@/utils/routeQuery'
import { NAME_MAX_LENGTH, nameLengthHint, nameTooLong } from '@/utils/nameLength'

import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { 
  Plus, Upload, Trash2, FolderOpen, LayoutGrid, List, Search,
  Database, Calendar, HardDrive, Edit2, Download, FileText,
  FileIcon, File, FileSpreadsheet, Image, Server, FolderHeart, Dna, FlaskConical, Loader2
} from 'lucide-vue-next'

// Components
import app_frame from '@/components/Layout/appFrame.vue'
import FileUploader from '@/components/common/fileUploader.vue'
import ResourceSort from '@/components/common/ResourceSort.vue'
import Protein3dMolstar from '@/components/molecule/protein3d_molstar.vue'
import MoleculePreview from '@/components/common/MoleculePreview.vue'
import { getFirstMoleculeInput } from '@/utils/rdkit'
import { inspectDelimitedText, parseDelimitedText, type DelimitedTextIssue } from '@/utils/delimitedText'

// UI Components
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { toast } from '@/components/ui/toast/use-toast'
// APIs
import { renameBackendDataset, deleteBackendDataset } from '@/api/genovaBackend'
import { filenameByteLength, MAX_FILENAME_BYTES } from '@/utils/uploadFileCheck'


const { t } = useI18n()
const route = useRoute()
const router = useRouter()

// Tab state
const activeTab = computed(() => route.query.tab === 'builtin' ? 'builtin' : 'mydata')
// An unknown tab or parameter is removed from the address bar, which shows the default tab.
useQueryCleanup(route, router, { tab: value => ['mydata', 'builtin'].includes(value), dataset_id: nonEmptyQueryValue })

// Tabs configuration
const tabs = [
  {
    value: 'mydata',
    label: 'data.我的数据',
    icon: FolderHeart,
    disabled: false
  },
  {
    value: 'builtin',
    label: 'data.内置数据库',
    icon: Server,
    disabled: false
  }
]

const updateTabUrl = (tabValue: string) => {
  router.push({ query: { ...route.query, tab: tabValue } })
}

const builtinDatasets = ref<any[]>([])
const resourceSort = ref<'time' | 'name'>('time')
const builtinSort = ref<'time' | 'name'>('time')
const sortedBuiltinDatasets = computed(() => [...builtinDatasets.value].sort((a, b) => builtinSort.value === 'name' ? a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }) : b.created_at.localeCompare(a.created_at)))
const referenceModeKeys: Record<string, string> = { ligand: 'ligand', residues: 'residueMode', coordinates: 'coordinates' }
const builtinLoaded = ref(false)
const dataLoaded = ref(false)
const builtinRefreshing = ref(false)
const isRefreshing = ref(false)
const builtinError = ref('')
const dataError = ref('')
let dataRequest = 0, builtinRequest = 0

// State
const isLoading = ref(false)
const dataList = ref<any[]>([])
const selectedItems = ref<string[]>([])
const viewMode = ref<'grid' | 'list'>('grid')
const searchQuery = ref('')
const fileTypeFilter = ref('all')
type ResourceCategory = 'raw' | 'prepared' | 'ligand' | 'other' | 'all'
const resourceCategory = ref<ResourceCategory>('raw')
const resourceCategories: Array<{ value: ResourceCategory; label: string; icon: any }> = [
  { value: 'raw', label: 'platform.rawStructures', icon: Dna },
  { value: 'prepared', label: 'platform.preparedStructure', icon: Database },
  { value: 'ligand', label: 'platform.ligandFiles', icon: FlaskConical },
  { value: 'other', label: 'platform.otherFiles', icon: File },
  { value: 'all', label: 'data.全部', icon: LayoutGrid },
]
const preparedFileRoles = new Set(['prepared_pocket_pdb', 'prepared_complex', 'effective_receptor', 'context_receptor', 'surfgen_protein_pdb', 'ecloudgen_protein_pdb', 'delete_protein_pdb'])
function categoryOf(item: any): Exclude<ResourceCategory, 'all'> {
  if (['prepared_receptor', 'protein_context'].includes(item.kind)) return 'prepared'
  const structures = (item.files || []).filter((file: any) => /\.(pdb|ent|cif|mmcif)$/i.test(file.original_filename))
  if (structures.length) return structures.every((file: any) => preparedFileRoles.has(file.file_role)) ? 'prepared' : 'raw'
  return (item.files || []).some((file: any) => /\.(sdf|mol|mol2)$/i.test(file.original_filename)) ? 'ligand' : 'other'
}
const categoryCounts = computed(() => {
  const counts = { raw: 0, prepared: 0, ligand: 0, other: 0, all: dataList.value.length }
  for (const item of dataList.value) counts[categoryOf(item)]++
  return counts
})
watch(resourceCategory, () => { fileTypeFilter.value = 'all'; selectedItems.value = [] })

// Dialog states
const showUploadDialog = ref(false)
const showPreviewDialog = ref(false)
const showRenameDialog = ref(false)
const showDeleteDialog = ref(false)
// Set from the first confirm click until the delete requests finish, so repeated clicks send nothing.
const deleting = ref(false)
let confirmedTarget: unknown = null

// Delete confirmation
const deleteTarget = ref<{
  type: 'single' | 'batch'
  item?: any
}>({
  type: 'single'
})

// Preview data
const previewData = ref<{
  file_id?: string
  dataset_id: string
  name: string
  smilesOptions: Array<{ value: string; label: string }>
  fileUrl?: string
  textContent?: string
  moleculeInput?: string
  contextDetails?: Record<string, string>
  preparedReceptor?: Record<string, any>
  context?: Record<string, any>
  resourceFiles?: any[]
}>({
  dataset_id: '',
  name: '',
  smilesOptions: [],
  fileUrl: '',
  textContent: '',
  moleculeInput: ''
})

const proteinViewerRef = ref<any>(null)
const isDelimitedFile = (name: string) => /\.(csv|tsv)$/i.test(name)
const csvPage = ref(1)
const selectedCsvRow = ref<number | null>(null)
const csvTable = computed((): { headers: string[]; rows: string[][]; error: boolean; issue: DelimitedTextIssue | null; warnings: DelimitedTextIssue[] } => {
  if (!isDelimitedFile(previewData.value.name)) return { headers: [], rows: [], error: false, issue: null, warnings: [] }
  const text = previewData.value.textContent || '', delimiter = /\.tsv$/i.test(previewData.value.name) ? '\t' : ','
  try {
    const table = parseDelimitedText(text, delimiter)
    // Broken quoting is reported with its line instead of showing a table whose lines were merged.
    const { error, warnings } = inspectDelimitedText(text, delimiter, table)
    if (error) return { headers: [], rows: [], error: true, issue: error, warnings: [] }
    return { ...table, error: false, issue: null, warnings }
  } catch {
    return { headers: [], rows: [], error: true, issue: inspectDelimitedText(text, delimiter).error, warnings: [] }
  }
})
const tableIssueText = (issue: DelimitedTextIssue) => translate(`platform.tableIssues.${issue.kind}`, { line: issue.line ?? 0, count: issue.count ?? 0 })
const csvSmilesColumn = computed(() => csvTable.value.headers.findIndex(header => ['smiles', 'smiles_canonical', 'gen_smiles'].includes(header.trim().toLowerCase())))
const csvPages = computed(() => Math.max(1, Math.ceil(csvTable.value.rows.length / 50)))
const csvPageRows = computed(() => csvTable.value.rows.slice((csvPage.value - 1) * 50, csvPage.value * 50))
const selectedCsvInput = computed(() => selectedCsvRow.value === null ? '' : (csvTable.value.rows[selectedCsvRow.value]?.[csvSmilesColumn.value] || '').trim())
watch(() => [previewData.value.dataset_id, previewData.value.file_id, previewData.value.textContent], () => {
  csvPage.value = 1
  selectedCsvRow.value = null
})

// Rename form
const renameForm = ref({
  datasetId: '',
  fileId: '',
  newName: '',
  extension: ''
})

// Computed
const filteredDataList = computed(() => {
  let filtered = resourceCategory.value === 'all' ? dataList.value : dataList.value.filter(item => categoryOf(item) === resourceCategory.value)
  
  // Search filter
  if (searchQuery.value.trim()) {
    const query = searchQuery.value.trim().toLowerCase()
    filtered = filtered.filter(item => 
      [item.name, ...(item.files || []).map((file: any) => file.original_filename)].some(name => name.toLowerCase().includes(query))
    )
  }
  
  // File type filter
  if (fileTypeFilter.value !== 'all') {
    filtered = filtered.filter(item => {
      if (fileTypeFilter.value === 'protein_context') return item.kind === 'protein_context'
      if (fileTypeFilter.value === 'prepared_receptor') return categoryOf(item) === 'prepared' && item.kind !== 'protein_context'
      if (categoryOf(item) === 'prepared') return false
      return (item.files || []).some((file: any) => {
      const ext = getFileExtension(file.original_filename).toLowerCase()
      if (fileTypeFilter.value === 'csv') {
        return ['csv', 'tsv', 'txt'].includes(ext)
      }
      if (fileTypeFilter.value === 'pdb') {
        return ['pdb', 'ent'].includes(ext)
      }
      if (fileTypeFilter.value === 'cif') {
        return ['cif', 'mmcif'].includes(ext)
      }
      return ext === fileTypeFilter.value
      })
    })
  }
  
  if (resourceSort.value === 'name') filtered = [...filtered].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }))
  return filtered
})

// 按时间分组的文件列表
const groupedDataList = computed(() => {
  if (resourceSort.value === 'name') return filteredDataList.value.length ? [{ label: 'data.全部', items: filteredDataList.value }] : []
  const now = new Date()
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
  const monthAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000)
  
  const groups = {
    today: { label: 'data.今日', items: [] as any[] },
    week: { label: 'data.最近一周', items: [] as any[] },
    month: { label: 'data.最近一月', items: [] as any[] },
    older: { label: 'data.更久', items: [] as any[] }
  }
  
  filteredDataList.value.forEach(item => {
    const itemDate = new Date(item.created_at)
    
    if (itemDate >= todayStart) {
      groups.today.items.push(item)
    } else if (itemDate >= weekAgo) {
      groups.week.items.push(item)
    } else if (itemDate >= monthAgo) {
      groups.month.items.push(item)
    } else {
      groups.older.items.push(item)
    }
  })
  
  // 只返回有内容的分组
  return Object.values(groups).filter(group => group.items.length > 0)
})

function selectDatasetFile(item: any, fileId: string) {
  const file = item.files.find((file: any) => file.id === fileId)
  if (file) {
    item.file_id = file.id; item.file_name = file.original_filename; item.file_size = file.size_bytes
    if (item.kind !== 'prepared_receptor') item.name = file.original_filename
  }
}

const loadDataList = async (invalidate = false) => {
  const identity = datacenterIdentity.value
  const request = ++dataRequest
  const queryKey = ['datacenter', ...identity, 'mydata', 'summary']
  const cached = queryClient.getQueryData<any[]>(queryKey)
  if (cached) {
    dataList.value = cached.map(item => ({ ...item }))
    dataLoaded.value = true
  }
  isLoading.value = !dataLoaded.value
  isRefreshing.value = true
  dataError.value = ''
  try {
    if (invalidate) {
      await queryClient.cancelQueries({ queryKey, exact: true })
      await queryClient.invalidateQueries({ queryKey, exact: true, refetchType: 'none' })
    }
    if (request !== dataRequest || identity !== datacenterIdentity.value) return
    const datasets = await queryClient.fetchQuery({
      queryKey, staleTime: 0, gcTime: 60_000, retry: false,
      queryFn: async ({ signal }) => (await listAllBackendDatasets({ summary: true, signal })).map((item: any) => {
        const resource = ['protein_context', 'prepared_receptor'].includes(item.kind)
        const files = (item.files || []).filter((file: any) => item.kind === 'prepared_receptor'
          ? ['prepared_complex', 'context_receptor'].includes(file.file_role)
          : item.kind === 'protein_context' ? file.file_role === 'effective_receptor' : true)
        const identity = item.kind === 'prepared_receptor' ? item.meta?.artifacts?.prepared_complex
          : item.meta?.artifacts?.effective_receptor
        const file = files.find((file: any) => file.id === identity?.file_id)
          || files.find((file: any) => file.file_role === 'source_structure') || files[0]
        return { ...item, files, dataset_id: item.id, file_id: file?.id, file_name: file?.original_filename, file_size: file?.size_bytes,
          name: resource ? item.name : file?.original_filename || item.name }
      }),
    })
    if (request !== dataRequest || identity !== datacenterIdentity.value) return
    dataList.value = datasets.map(item => ({ ...item }))
    dataLoaded.value = true
  } catch (error: any) {
    if (request !== dataRequest || identity !== datacenterIdentity.value || isCancelledError(error)) return
    dataError.value = `${t('data.加载失败')}: ${displayErrorMessage(error, translate('platform.unknownError'))}`
  } finally {
    if (request === dataRequest && identity === datacenterIdentity.value) {
      isLoading.value = false
      isRefreshing.value = false
    }
  }
}

const loadBuiltinDatasets = async () => {
  const identity = datacenterIdentity.value
  const request = ++builtinRequest
  const queryKey = ['datacenter', ...identity, 'builtin', 'summary']
  const cached = queryClient.getQueryData<any[]>(queryKey)
  if (cached) {
    builtinDatasets.value = cached.map(item => ({ ...item }))
    builtinLoaded.value = true
  }
  builtinRefreshing.value = true
  builtinError.value = ''
  try {
    const datasets = await queryClient.fetchQuery({
      queryKey, staleTime: 0, gcTime: 60_000, retry: false,
      queryFn: async ({ signal }) => {
        const res = await listBuiltinBackendDatasets({ summary: true, signal })
        return res.data.map((item: any) => ({
          ...item, dataset_id: item.id, file_id: item.files?.[0]?.id,
          name: item.files?.[0]?.original_filename || item.name,
          file_size: item.files?.[0]?.size_bytes,
        }))
      },
    })
    if (request !== builtinRequest || identity !== datacenterIdentity.value) return
    builtinDatasets.value = datasets.map(item => ({ ...item }))
    builtinLoaded.value = true
  } catch (error: any) {
    if (request !== builtinRequest || identity !== datacenterIdentity.value || isCancelledError(error)) return
    builtinError.value = `${t('data.加载失败')}: ${displayErrorMessage(error, translate('platform.unknownError'))}`
  } finally {
    if (request === builtinRequest && identity === datacenterIdentity.value) builtinRefreshing.value = false
  }
}

const getFileIcon = (fileName: string) => {
  const ext = getFileExtension(fileName).toLowerCase()
  switch (ext) {
    case 'csv':
    case 'tsv':
    case 'txt': return FileSpreadsheet
    case 'pdf': return FileText
    case 'png':
    case 'jpg':
    case 'jpeg': return Image
    case 'sdf':
    case 'pdb':
    case 'ent':
    case 'cif':
    case 'mmcif': return FileIcon
    default: return File
  }
}

const getFileIconColor = (fileName: string) => {
  const ext = getFileExtension(fileName).toLowerCase()
  switch (ext) {
    case 'csv':
    case 'tsv':
    case 'txt': return 'text-emerald-600'
    case 'pdf': return 'text-red-600'
    case 'png':
    case 'jpg':
    case 'jpeg': return 'text-purple-600'
    case 'sdf': return 'text-violet-600'
    case 'pdb':
    case 'ent': return 'text-indigo-600'
    case 'cif':
    case 'mmcif': return 'text-blue-600'
    default: return 'text-gray-600'
  }
}

const getFileExtension = (fileName: string) => {
  return fileName.split('.').pop() || ''
}

const getBaseName = (fileName: string) => {
  const parts = fileName.split('.')
  return parts.length > 1 ? parts.slice(0, -1).join('.') : fileName
}

const getFileTypeBadgeClass = (ext: string) => {
  const extLower = ext.toLowerCase()
  switch (extLower) {
    case 'csv':
    case 'tsv':
    case 'txt': return 'bg-emerald-100 text-emerald-800 border-emerald-200'
    case 'sdf': return 'bg-violet-100 text-violet-800 border-violet-200'
    case 'pdb':
    case 'ent': return 'bg-indigo-100 text-indigo-800 border-indigo-200'
    case 'cif':
    case 'mmcif': return 'bg-blue-100 text-blue-800 border-blue-200'
    case 'pdf': return 'bg-red-100 text-red-800 border-red-200'
    case 'png':
    case 'jpg':
    case 'jpeg': return 'bg-purple-100 text-purple-800 border-purple-200'
    default: return 'bg-gray-100 text-gray-800 border-gray-200'
  }
}

const formatDate = (dateString: string) => {
  if (!dateString) return '-'
  try {
    return new Date(dateString).toLocaleDateString(i18n.global.locale.value)
  } catch {
    return '-'
  }
}

const formatFileSize = (bytes: number) => {
  if (!bytes) return '-'
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return Math.round(bytes / Math.pow(1024, i) * 100) / 100 + ' ' + sizes[i]
}

const getSourceDisplay = (source: any) => {
  if (!source) return '-'
  if (typeof source === 'string') return source
  if (source.module) {
    const moduleMap: { [key: string]: string } = {
      'rescoring': t('data.重打分'),
      'docking': t('data.分子对接'),
      'admet': t('data.ADMET预测'),
      'ligand_prep': t('data.配体准备'),
      'qsar': t('data.QSAR建模'),
      'qsar_application': t('data.QSAR应用'),
      'spectrum_ai': t('data.光谱AI'),
      'datacenter': t('data.数据中心')
    }
    return moduleMap[source.module] || source.module
  }
  return t('data.未知来源')
}

const isPdf = (fileName: string) => {
  const ext = getFileExtension(fileName).toLowerCase()
  return ext === 'pdf'
}

const isPdb = (fileName: string) => {
  const ext = getFileExtension(fileName).toLowerCase()
  return ['pdb', 'ent'].includes(ext)
}

const isCif = (fileName: string) => {
  const ext = getFileExtension(fileName).toLowerCase()
  return ['cif', 'mmcif'].includes(ext)
}

const isStructure = (fileName: string) => {
  return isPdb(fileName) || isCif(fileName)
}

const isImage = (fileName: string) => {
  const ext = getFileExtension(fileName).toLowerCase()
  return ['png', 'jpg', 'jpeg'].includes(ext)
}

const isSpecialFile = (fileName: string) => {
  return isPdf(fileName) || isStructure(fileName) || isImage(fileName)
}

const toggleSelection = (itemId: string, checked: boolean) => {
  if (checked) {
    selectedItems.value.push(itemId)
  } else {
    const index = selectedItems.value.indexOf(itemId)
    if (index > -1) {
      selectedItems.value.splice(index, 1)
    }
  }
}

function artifactLabel(file: any): string {
  const match = /^(surfgen|delete|ecloudgen|epso)_(.+)$/.exec(file.file_role)
  const role = match?.[2] || file.file_role
  const labels: Record<string, string> = {
    prepared_complex: 'preparedComplex', context_receptor: 'apoReceptor', protein_pdb: 'apoReceptor',
    reference_ligand: 'referenceLigand', report: 'report', atom_map: 'artifactMapping',
    context_receptor_map: 'artifactMapping', 'model_receptor_map.json': 'artifactMapping',
    component_manifest: 'artifactManifest', cache: 'artifactCache', input_features: 'artifactFeatures',
  }
  const label = labels[role] ? t(`platform.${labels[role]}`) : file.original_filename
  return match ? `${match[1]} · ${label}` : label
}

function contextDetails(item: any, prepared?: any, source?: any): Record<string, string> {
  const meta = item.meta || {}
  prepared ||= dataList.value.find(row => row.dataset_id === meta.prepared_receptor_id)
  const identity = prepared?.meta?.source
  source ||= [...dataList.value, ...builtinDatasets.value].find(row => row.dataset_id === identity?.dataset_id || row.id === identity?.dataset_id)
  const box = meta.site?.box
  const mode = ({ source_components: 'ligand', prepared_residues: 'residues', coordinates: 'coordinates' } as Record<string, string>)[meta.site?.anchor?.kind]
  const details: Record<string, string> = {
    [t('platform.sourceLabel')]: source?.files?.find((file: any) => file.id === identity?.file_id)?.original_filename || meta.source_filename || '—',
  }
  details[t('platform.preparedStructure')] = prepared?.name || meta.prepared_receptor_id
  details[t('platform.mode')] = mode ? t('platform.' + referenceModeKeys[mode]) : '—'
  details[t('platform.centerCoordinatesAngstrom')] = box?.center ? box.center.map((value: number) => Number(value).toFixed(3)).join(', ') : '—'
  details[t('platform.size')] = box?.size ? box.size.map((value: number) => Number(value).toFixed(3)).join(' × ') + ' Å' : '—'
  details[t('platform.referenceLigand')] = meta.generation_reference ? t('platform.boundReference') : t('platform.noReference')
  return details
}

let previewRequest = 0
watch([proteinViewerRef, () => previewData.value.textContent, () => previewData.value.context], async ([viewer, content, context]) => {
  if (!viewer || !showPreviewDialog.value || !isStructure(previewData.value.name) || !context && !content) return
  const request = previewRequest
  try {
    if (context) await viewer.loadContext(context, previewData.value.preparedReceptor)
    else await viewer.loadStructure(content, isCif(previewData.value.name) ? 'mmcif' : 'pdb', false, true)
  } catch (error: any) {
    if (request !== previewRequest) return
    toast({ title: t('data.加载预览失败'), description: requestErrorMessage(error, translate('platform.previewErrors.content')), variant: 'destructive' })
  }
}, { flush: 'post' })
// Already-rendered previews keep showing after revoke; this only releases the Blob.
const releasePreviewUrl = () => { if (previewData.value.fileUrl) URL.revokeObjectURL(previewData.value.fileUrl) }
watch(showPreviewDialog, open => { if (!open) { previewRequest++; releasePreviewUrl() } })
// Leaving the page also invalidates an unfinished download, so a late response creates no Blob URL.
onBeforeUnmount(() => { dataRequest++; builtinRequest++; previewRequest++; releasePreviewUrl() })
const openDataPreview = async (item: any) => {
  const requestId = ++previewRequest
  try {
    releasePreviewUrl()
    previewData.value = {
      dataset_id: item.dataset_id,
      file_id: item.file_id,
      name: item.kind === 'protein_context' ? `${item.name}.pdb` : item.kind === 'prepared_receptor' ? `${item.name}.${getFileExtension(item.file_name)}` : item.name,
      smilesOptions: [],
      fileUrl: '',
      textContent: '',
      moleculeInput: ''
    }
    if (item.kind === 'protein_context') {
      showPreviewDialog.value = true
      await nextTick()
      if (requestId !== previewRequest) return
      const dataset = (await getBackendDataset(item.dataset_id)).data
      const prepared = (await getBackendDataset(dataset.meta.prepared_receptor_id)).data
      const sourceId = prepared?.meta?.source?.dataset_id
      const source = sourceId ? (await getBackendDataset(sourceId)).data : undefined
      if (requestId !== previewRequest) return
      previewData.value.resourceFiles = [...prepared.files, ...dataset.files].map(file => ({ ...file, dataset_id: prepared.files.includes(file) ? prepared.id : dataset.id }))
      previewData.value.preparedReceptor = prepared.meta
      previewData.value.contextDetails = contextDetails(dataset, prepared, source)
      previewData.value.context = { ...dataset.meta, id: dataset.id, name: dataset.name }
      return
    }
    if (item.kind === 'prepared_receptor') {
      const dataset = (await getBackendDataset(item.dataset_id)).data
      if (requestId !== previewRequest) return
      previewData.value.resourceFiles = dataset.files.map(file => ({ ...file, dataset_id: dataset.id }))
    }
    const size = item.files?.find((file: any) => file.id === item.file_id)?.size_bytes ?? item.file_size
    // The preview reads the whole file into the browser; large files are downloaded instead.
    if (size > 20 * 1024 * 1024) {
      toast({ title: t('data.预览文件过大'), variant: 'destructive' })
      return
    }
    const res = await downloadBackendDataset(item.dataset_id, item.file_id)
    if (requestId !== previewRequest) return
    const blob = res.data as Blob

    if (isPdf(item.name) || isImage(item.name)) {
      previewData.value.fileUrl = URL.createObjectURL(blob)
      showPreviewDialog.value = true
      return
    }

    const text = await blob.text()
    if (requestId !== previewRequest) return
    previewData.value.textContent = text
    previewData.value.moleculeInput = isDelimitedFile(previewData.value.name) || isStructure(previewData.value.name) ? '' : getFirstMoleculeInput(previewData.value.textContent, previewData.value.name)

    if (isStructure(previewData.value.name)) {
      showPreviewDialog.value = true
      return
    }
    
    showPreviewDialog.value = true
  } catch (error: any) {
    if (requestId !== previewRequest) return
    console.error('Failed to load preview data:', error)
    // The file was removed elsewhere: say so and drop it from the list.
    if (isNotFoundError(error)) {
      showPreviewDialog.value = false
      toast({ title: translate('platform.previewErrors.fileGone'), variant: 'destructive' })
      void loadDataList(true)
      return
    }
    toast({
      title: t('data.加载预览失败'),
      description: requestErrorMessage(error, translate('platform.previewErrors.load')),
      variant: 'destructive'
    })
  }
}

const openContext = (item: any, path: string) => router.push({
  path,
  query: { protein_context_id: item.dataset_id },
})

const editContext = (item: any) => router.push({
  path: '/protein-preparation',
  query: { context_id: item.dataset_id },
})

const openRenameDialog = (item: any) => {
  // Protein contexts have a plain name; files keep their extension.
  const fileId = item.kind === 'protein_context' ? '' : item.file_id || ''
  const dot = fileId ? item.name.lastIndexOf('.') : -1
  renameForm.value = {
    datasetId: item.dataset_id,
    fileId,
    newName: dot > 0 ? item.name.slice(0, dot) : item.name,
    extension: dot > 0 ? item.name.slice(dot + 1) : ''
  }
  showRenameDialog.value = true
}

const renameName = computed(() => {
  const { extension, newName } = renameForm.value
  return newName.trim() + (extension ? '.' + extension : '')
})
const renameFilenameBytes = computed(() => filenameByteLength(renameName.value))
const renameNameTooLong = computed(() => renameForm.value.fileId
  ? renameFilenameBytes.value > MAX_FILENAME_BYTES
  : nameTooLong(renameForm.value.newName))

const confirmRename = async () => {
  if (!renameForm.value.newName.trim() || renameNameTooLong.value) return
  try {
    const { datasetId, fileId } = renameForm.value
    await renameBackendDataset(datasetId, {
      name: renameName.value,
      ...(fileId ? { file_id: fileId } : {})
    })
    
    toast({
      title: t('data.重命名成功'),
      variant: 'default'
    })
    
    showRenameDialog.value = false
    void loadDataList(true)
  } catch (error: any) {
    console.error('Rename failed:', error)
    toast({
      title: t('data.重命名失败'),
      description: requestErrorMessage(error),
      variant: 'destructive'
    })
  }
}

const downloadFile = async (item: any) => {
  try {
    const identity = (item.kind === 'protein_context' ? item.meta : item.context)?.artifacts.effective_receptor
    const datasetId = identity?.dataset_id || item.dataset_id
    const fileId = identity?.file_id || item.file_id
    const filename = identity
      ? (await getBackendDataset(datasetId)).data.files.find(file => file.id === fileId)!.original_filename
      : item.file_name || item.name
    const res = await downloadBackendDataset(datasetId, fileId)
    const url = URL.createObjectURL(res.data)
    const link = document.createElement('a')
    link.href = url
    link.download = identity || item.kind === 'prepared_receptor' ? `${item.context?.name || item.name}.${getFileExtension(filename)}` : item.name
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  } catch (error: any) {
    console.error('Download failed:', error)
    toast({
      title: t('data.下载失败'),
      description: requestErrorMessage(error),
      variant: 'destructive'
    })
  }
}

const confirmDeleteSingle = (item: any) => {
  deleteTarget.value = {
    type: 'single',
    item
  }
  showDeleteDialog.value = true
}

const confirmBatchDelete = () => {
  if (selectedItems.value.length === 0) {
    toast({
      title: t('data.请先选择数据'),
      variant: 'destructive'
    })
    return
  }
  
  deleteTarget.value = {
    type: 'batch'
  }
  showDeleteDialog.value = true
}

const handleDeleteConfirm = async () => {
  // One confirmation per opened dialog: clicks that land while it closes are ignored even after the request finished.
  if (deleting.value || confirmedTarget === deleteTarget.value) return
  confirmedTarget = deleteTarget.value
  deleting.value = true
  showDeleteDialog.value = false
  try {
    if (deleteTarget.value.type === 'single' && deleteTarget.value.item) {
      await deleteSingleItem(deleteTarget.value.item.dataset_id)
    } else if (deleteTarget.value.type === 'batch') {
      await batchDelete()
    }
  } finally {
    deleting.value = false
  }
}

// Deleting is idempotent: data that is already gone counts as deleted.
const deleteDataset = async (datasetId: string) => {
  try {
    await deleteBackendDataset(datasetId)
  } catch (error) {
    if (!isNotFoundError(error)) throw error
  }
}

const deleteSingleItem = async (datasetId: string) => {
  try {
    await deleteDataset(datasetId)
    toast({
      title: t('data.删除成功'),
      variant: 'default'
    })
    void loadDataList(true)
  } catch (error: any) {
    console.error('Delete failed:', error)
    toast({
      title: t('data.删除失败'),
      description: inUseMessage(error) || requestErrorMessage(error),
      variant: 'destructive'
    })
  }
}

const inUseMessage = (error: any) => {
  const detail = error?.response?.data?.detail
  return ['DATASET_IN_USE_BY_AGENT', 'DATASET_IN_USE_BY_CONTEXT', 'DATASET_IN_USE_BY_JOB'].includes(detail) ? t(`data.${detail}`) : ''
}

const batchDelete = async () => {
  try {
    const ids = [...selectedItems.value]
    const outcomes: PromiseSettledResult<void>[] = []
    // At most four requests at a time, so a large selection does not flood the server.
    for (let i = 0; i < ids.length; i += 4) outcomes.push(...await Promise.allSettled(ids.slice(i, i + 4).map(deleteDataset)))
    const failure = outcomes.find(outcome => outcome.status === 'rejected')
    if (failure) throw failure.reason
    
    selectedItems.value = []
    toast({
      title: t('data.批量删除成功'),
      variant: 'default'
    })
    void loadDataList(true)
  } catch (error: any) {
    console.error('Batch delete failed:', error)
    toast({
      title: t('data.部分数据删除失败'),
      description: inUseMessage(error) || requestErrorMessage(error),
      variant: 'destructive'
    })
    void loadDataList(true)
  }
}

const handleUploadComplete = ({ uploaded, failed, canceled }: { uploaded: number; failed: number; canceled?: boolean }) => {
  if (canceled) toast({ title: translate('platform.uploadCancel.done'), description: uploaded ? translate('platform.uploadCancel.partial', { count: uploaded }) : undefined })
  if (uploaded) {
    if (!canceled) toast({ title: t('result.上传成功'), variant: 'default' })
    void loadDataList(true)
  }
  if (!failed) showUploadDialog.value = false
}

const handleUploadError = (error: string) => {
  toast({
    title: t('common.上传失败'),
    description: error,
    variant: 'destructive'
  })
}

watch([() => route.query.dataset_id, dataLoaded], ([id, loaded]) => {
  if (!id || !loaded) return
  const item = dataList.value.find(row => row.dataset_id === String(id))
  if (item) void openDataPreview(item)
}, { immediate: true })

// Lifecycle
watch([datacenterIdentity, activeTab], ([identity, tab], previous) => {
  if (previous && identity !== previous[0]) {
    dataRequest++; builtinRequest++; previewRequest++
    dataList.value = []; builtinDatasets.value = []; selectedItems.value = []
    dataLoaded.value = false; builtinLoaded.value = false
    isLoading.value = false; isRefreshing.value = false; builtinRefreshing.value = false
    dataError.value = ''; builtinError.value = ''
    releasePreviewUrl()
    previewData.value = { dataset_id: '', name: '', smilesOptions: [] }
    showPreviewDialog.value = false; showRenameDialog.value = false; showDeleteDialog.value = false; showUploadDialog.value = false
  }
  if (!identity[0]) return
  if (tab === 'builtin') void loadBuiltinDatasets()
  else void loadDataList()
}, { immediate: true })

</script>

<style scoped>
/* Custom styles if needed */
</style>

<route lang="yaml">
meta:
  layout: blank
</route>
