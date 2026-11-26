<template>
  <div 
    class="relative w-full h-full" 
    :class="{ 'fixed left-0 top-0 w-screen h-screen z-[50]': full_screen_type }"
  >
    <div 
      :id="canvas_id" 
      ref="molstar_ref" 
      class="drugflow_molstar w-full h-full min-w-[300px] min-h-[300px]" 
      :class="{ 'drugflow_molstar_no_sequence': !props.if_sequence_panel }"
    />
    
    <!-- Toolbar -->
    <div 
      v-show="props.show_tool && show_tool" 
      class="top-2 w-full z-[50] flex items-center justify-between gap-2 px-2"
      :class="{ 'fixed top-0 left-0': full_screen_type, 'absolute': !full_screen_type }"
    >
      <div v-show="!show_prolif" class="mx-auto">
        <!-- Action Tools (Centered) -->
        <div class="flex items-center gap-1">
          <div class="flex items-center gap-1">
            <Popover v-model:open="selection_tools_open">
              <div class="relative group">
                <PopoverTrigger as-child>
                  <Button 
                    variant="ghost" 
                    size="icon" 
                    :class="cn(
                      'h-8 w-8 rounded-md hover:bg-accent hover:text-accent-foreground',
                      selection_tools_open && 'bg-accent text-accent-foreground'
                    )"
                  >
                    <SquareDashedMousePointer class="h-4 w-4" />
                    <span class="sr-only">{{ t('molstar.toolbar.selection') }}</span>
                  </Button>
                </PopoverTrigger>
                <!-- Custom Tooltip -->
                <div class="absolute left-1/2 -translate-x-1/2 top-full mt-2 px-2 py-1 bg-popover text-popover-foreground text-xs rounded-md shadow-md opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-opacity duration-200 whitespace-nowrap z-50 pointer-events-none">
                  {{ t('molstar.toolbar.selection') }}
                </div>
              </div>
              <PopoverContent class="w-[400px]">
                <div class="grid gap-4" :class="props.ligand_only ? 'grid-cols-1' : 'grid-cols-[180px_1fr]'">
                  <!-- Left Column: Granularity & Operations -->
                  <div class="space-y-4">
                    <!-- Granularity -->
                    <div class="space-y-2">
                      <h4 class="font-medium text-sm">{{ t('molstar.selection.granularity') }}</h4>
                      <RadioGroup v-model="granularity" @update:model-value="set_granularity" class="space-y-1">
                        <div class="flex items-center space-x-2">
                          <RadioGroupItem id="chain" value="chain" />
                          <Label for="chain" class="text-xs">{{ t('molstar.selection.chain') }}</Label>
                        </div>
                        <div class="flex items-center space-x-2">
                          <RadioGroupItem id="residue" value="residue" />
                          <Label for="residue" class="text-xs">{{ t('molstar.selection.residue') }}</Label>
                        </div>
                        <div class="flex items-center space-x-2">
                          <RadioGroupItem id="element" value="element" />
                          <Label for="element" class="text-xs">{{ t('molstar.selection.atom') }}</Label>
                        </div>
                      </RadioGroup>
                    </div>

                    <Separator />

                    <!-- Operations -->
                    <div class="space-y-1">
                      <h4 class="font-medium text-sm mb-2">{{ t('molstar.selection.operations') }}</h4>
                      <Button variant="ghost" size="sm" class="w-full justify-start text-xs h-7" @click="select_all()">
                        {{ t('molstar.selection.selectAll') }}
                      </Button>
                      <Button variant="ghost" size="sm" class="w-full justify-start text-xs h-7" @click="select_none()">
                        {{ t('molstar.selection.selectNone') }}
                      </Button>
                      <Button variant="ghost" size="sm" class="w-full justify-start text-xs h-7" @click="invert_select()">
                        {{ t('molstar.selection.invertSelection') }}
                      </Button>
                    </div>

                    <Separator />

                    <!-- Expand Selection -->
                    <div class="space-y-2">
                      <h4 class="font-medium text-sm">{{ t('molstar.selection.expandSelection') }}</h4>
                      <div class="flex items-center gap-2">
                        <Input 
                          v-model="expand_number" 
                          type="number"
                          :min="1" 
                          :max="10" 
                          class="h-7 text-xs flex-1"
                        />
                        <span class="text-xs text-muted-foreground">Å</span>
                        <Button size="sm" class="h-7 px-2 text-xs" @click="expand_selection">
                          {{ t('molstar.selection.apply') }}
                        </Button>
                      </div>
                    </div>
                  </div>

                  <!-- Right Column: Quick Select -->
                  <div v-if="!props.ligand_only" class="space-y-1 border-l pl-4">
                    <h4 class="font-medium text-sm mb-2">{{ t('molstar.selection.quickSelect') }}</h4>
                    <div class="max-h-[320px] overflow-y-auto space-y-1">
                      <!-- Chains -->
                      <Button 
                        variant="ghost" 
                        size="sm" 
                        class="w-full justify-start text-xs h-7" 
                        @click="quick_select(undefined, 'chains')"
                      >
                        {{ t('molstar.selection.allChains') }}
                      </Button>
                      <Button 
                        v-for="item in pdb_info.chain" 
                        :key="item.key"
                        variant="ghost" 
                        size="sm" 
                        class="w-full justify-start text-xs h-7 pl-4" 
                        @click="quick_select(item)"
                      >
                        {{ t('molstar.selection.chain') }} {{ item.auth_asym_id }}
                      </Button>
                      
                      <!-- Ligands -->
                      <template v-if="pdb_info.ligand.length">
                        <Separator class="my-2" />
                        <Button 
                          variant="ghost" 
                          size="sm" 
                          class="w-full justify-start text-xs h-7" 
                          @click="quick_select(undefined, 'ligands')"
                        >
                          {{ t('molstar.selection.allLigands') }}
                        </Button>
                        <Button 
                          v-for="item in pdb_info.ligand" 
                          :key="item.key"
                          variant="ghost" 
                          size="sm" 
                          class="w-full justify-start text-xs h-7 pl-4" 
                          @click="quick_select(item)"
                        >
                          {{ item.auth_asym_id }}:{{ item.residue_name }}:{{ item.auth_residue_number }}
                        </Button>
                      </template>
                      
                      <!-- Water -->
                      <template v-if="pdb_info.water.length">
                        <Separator class="my-2" />
                        <Button 
                          variant="ghost" 
                          size="sm" 
                          class="w-full justify-start text-xs h-7" 
                          @click="quick_select(undefined, 'water')"
                        >
                          {{ t('molstar.selection.allWater') }}
                        </Button>
                      </template>
                    </div>
                  </div>
                </div>
              </PopoverContent>
            </Popover>
          </div>
          
          <div class="relative group">
            <Button variant="ghost" size="icon" class="h-8 w-8 rounded-md hover:bg-accent hover:text-accent-foreground" @click="make_screenshot">
              <Camera class="h-4 w-4" />
              <span class="sr-only">{{ t('molstar.toolbar.screenshot') }}</span>
            </Button>
            <div class="absolute left-1/2 -translate-x-1/2 top-full mt-2 px-2 py-1 bg-popover text-popover-foreground text-xs rounded-md shadow-md opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-opacity duration-200 whitespace-nowrap z-50 pointer-events-none">
              {{ t('molstar.toolbar.screenshot') }}
            </div>
          </div>
          
          <div class="relative group">
            <Button variant="ghost" size="icon" class="h-8 w-8 rounded-md hover:bg-accent hover:text-accent-foreground" @click="reset_camera">
              <ScanEye class="h-4 w-4" />
              <span class="sr-only">{{ t('molstar.toolbar.center') }}</span>
            </Button>
            <div class="absolute left-1/2 -translate-x-1/2 top-full mt-2 px-2 py-1 bg-popover text-popover-foreground text-xs rounded-md shadow-md opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-opacity duration-200 whitespace-nowrap z-50 pointer-events-none">
              {{ t('molstar.toolbar.center') }}
            </div>
          </div>
          
          <div class="relative group">
            <Button variant="ghost" size="icon" class="h-8 w-8 rounded-md hover:bg-accent hover:text-accent-foreground" @click="toggle_spin">
              <Rotate3D class="h-4 w-4" />
              <span class="sr-only">{{ t('molstar.toolbar.rotate') }}</span>
            </Button>
            <div class="absolute left-1/2 -translate-x-1/2 top-full mt-2 px-2 py-1 bg-popover text-popover-foreground text-xs rounded-md shadow-md opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-opacity duration-200 whitespace-nowrap z-50 pointer-events-none">
              {{ t('molstar.toolbar.rotate') }}
            </div>
          </div>
          
          <div class="relative group">
            <Button variant="ghost" size="icon" class="h-8 w-8 rounded-md hover:bg-accent hover:text-accent-foreground" @click="full_screen">
              <Fullscreen class="h-4 w-4" />
              <span class="sr-only">{{ t('molstar.toolbar.fullscreen') }}</span>
            </Button>
            <div class="absolute left-1/2 -translate-x-1/2 top-full mt-2 px-2 py-1 bg-popover text-popover-foreground text-xs rounded-md shadow-md opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-opacity duration-200 whitespace-nowrap z-50 pointer-events-none">
              {{ t('molstar.toolbar.fullscreen') }}
            </div>
          </div>
        </div>
        
      </div>
      
      <div class="ml-auto flex items-center gap-1">
        <!-- 2D Interaction Button -->
        <div v-if="!props.ligand_only" class="relative group">
          <Button 
            size="sm" 
            variant="outline" 
            :class="cn(
              'h-8 px-2 shadow-none text-xs disabled:cursor-not-allowed disabled:opacity-50'
            )"
            @click="show_interaction_dialog" 
            :disabled="!props.interaction_2d"
            :aria-pressed="show_prolif"
          >
            {{ show_prolif ? '3D' : '2D' }}
          </Button>
          <div class="absolute left-1/2 -translate-x-1/2 top-full mt-2 px-2 py-1 bg-popover text-popover-foreground text-xs rounded-md shadow-md opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-opacity duration-200 whitespace-nowrap z-50 pointer-events-none">
            {{ t('molstar.toolbar.interaction') }}
          </div>
        </div>
        
        <!-- Structure Tree Toggle Button -->
        <div v-show="!show_prolif" class="relative group">
          <Button 
            variant="outline" 
            size="icon" 
            :class="cn(
              'h-8 w-8 shadow-none',
              structure_tree_open && 'bg-primary/15 text-primary border-primary/30'
            )"
            @click="structure_tree_open = !structure_tree_open"
          >
            <Network class="h-4 w-4" />
            <span class="sr-only">{{ t('molstar.toolbar.structureTree') }}</span>
          </Button>
          <!-- Custom Tooltip -->
          <div class="absolute left-1/2 -translate-x-1/2 top-full mt-2 px-2 py-1 bg-popover text-popover-foreground text-xs rounded-md shadow-md opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-opacity duration-200 whitespace-nowrap z-50 pointer-events-none">
            {{ t('molstar.toolbar.structureTree') }}
          </div>
        </div>
      </div>
    </div>

    <div v-if="show_prolif" class="absolute inset-0 z-40 bg-white pt-12">
      <interaction_2d_viewer :diagram="props.interaction_2d?.diagram" :status="props.interaction_2d?.status" :error="props.interaction_2d?.error" @retry="emit('request-2d', true)" @residue-select="select_2d_residue" />
    </div>

    <!-- WebGL Error Dialog -->
    <AlertDialog v-model:open="webgl_error_dialog">
      <AlertDialogContent class="max-w-2xl">
        <AlertDialogHeader>
          <AlertDialogTitle class="text-xl text-destructive flex items-center gap-2">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            {{ t('molstar.webglError.title') }}
          </AlertDialogTitle>
          <AlertDialogDescription class="space-y-4 text-base">
            <p>{{ t('molstar.webglError.description') }}</p>
            <ul class="list-disc list-inside space-y-2 pl-2">
              <li>{{ t('molstar.webglError.solutions.updateBrowser') }}</li>
              <li>{{ t('molstar.webglError.solutions.enableWebGL') }}</li>
              <li>{{ t('molstar.webglError.solutions.tryAnotherBrowser') }}</li>
              <li>{{ t('molstar.webglError.solutions.checkGraphics') }}</li>
            </ul>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogAction @click="webgl_error_dialog = false">
            {{ t('molstar.webglError.confirm') }}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

    <!-- Right Side Structure Tree Panel -->
    <div 
      v-if="!show_prolif && structure_tree_open && structure_tree.length > 0 && init_show_tree"
      class="top-12 right-2 z-[49] max-h-[calc(100%-6rem)] backdrop-blur-sm bg-white/80 dark:bg-slate-900/80 rounded-lg border border-slate-200 overflow-hidden"
      :class="{ 'fixed': full_screen_type, 'absolute': !full_screen_type }"
    >
      <ScrollArea class="h-full max-h-[calc(100vh-6rem)]">
        <div class="p-2 space-y-2">
          <!-- Selection Status and Quick Create -->
          <div 
            v-if="has_selection" 
            class="flex items-center justify-between gap-2 p-2 rounded bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800"
          >
            <div class="flex items-center gap-1 flex-1 min-w-0">
              <span class="text-yellow-700 dark:text-yellow-400 text-xs font-medium truncate">
                {{ t('molstar.structureTree.selectionActive') }}
              </span>
            </div>
            <DropdownMenu>
              <DropdownMenuTrigger as-child>
                <Button 
                  size="sm" 
                  variant="outline" 
                  class="h-6 px-2 text-xs border-yellow-300 hover:bg-yellow-100 dark:border-yellow-700 dark:hover:bg-yellow-900/40"
                >
                  <Plus class="h-3 w-3 mr-1" />
                  {{ t('molstar.structureTree.addRepr') }}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" class="w-48">
                <DropdownMenuItem @click="create_component_from_selection('cartoon')">
                  cartoon
                </DropdownMenuItem>
                <DropdownMenuItem @click="create_component_from_selection('ball-and-stick')">
                  ball-and-stick
                </DropdownMenuItem>
                <DropdownMenuItem @click="create_component_from_selection('gaussian-surface')">
                  surface
                </DropdownMenuItem>
                <DropdownMenuItem @click="create_component_from_selection('spacefill')">
                  spacefill
                </DropdownMenuItem>
                <DropdownMenuItem @click="create_component_from_selection('line')">
                  line
                </DropdownMenuItem>
                <DropdownMenuItem @click="create_component_from_selection('label')">
                  label
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
          
          <!-- Empty State -->
          <div v-if="structure_tree.length === 0" class="text-xs text-muted-foreground">
            {{ t('molstar.structureTree.noStructures') }}
          </div>
          
          <!-- Structures Loop -->
          <div v-for="structure in structure_tree" :key="structure.ref" class="space-y-1 border rounded p-2 ">
            <!-- Structure Header -->
            <div class="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                class="h-5 w-5 p-0"
                @click="toggle_structure_collapsed(structure.ref)"
              >
                <ChevronDown v-if="!is_structure_collapsed(structure.ref)" class="h-3 w-3" />
                <ChevronRight v-else class="h-3 w-3" />
              </Button>
              
              <Button
                variant="ghost"
                size="sm"
                class="h-5 w-5 p-0"
                @click="toggle_structure_visibility(structure.ref)"
              >
                <Eye v-if="structure_visibility.get(structure.ref)" class="h-3 w-3" />
                <EyeOff v-else class="h-3 w-3" />
              </Button>
              
              <!-- Color indicator (if color is provided) -->
              <div 
                v-if="structure_color_map.get(structure.ref)"
                :style="{ background: structure_color_map.get(structure.ref) }"
                class="w-3 h-3 border border-slate-300 shrink-0 rounded-sm"
              ></div>
              
              <span class="font-medium text-xs flex-1">{{ structure_label_map.get(structure.ref) || structure.label }}</span>
              
              <!-- Add Component Menu -->
              <Popover>
                <PopoverTrigger as-child>
                  <Button
                    variant="ghost"
                    size="sm"
                    class="h-5 px-0 text-xs"
                  >
                    <Plus class="h-3 w-3 mr-1" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent class="w-40" side="left">
                  <div class="space-y-1">
                    <h5 class="font-medium text-xs mb-2">{{ t('molstar.structureTree.addComponent') }}</h5>
                    <Button 
                      variant="ghost" 
                      size="sm" 
                      class="w-full justify-start text-xs h-6"
                      @click="add_component_to_structure(structure.ref, 'polymer')"
                    >
                      {{ t('molstar.structureTree.polymer') }}
                    </Button>
                    <Button 
                      variant="ghost" 
                      size="sm" 
                      class="w-full justify-start text-xs h-6"
                      @click="add_component_to_structure(structure.ref, 'ligand')"
                    >
                      {{ t('molstar.structureTree.ligand') }}
                    </Button>
                    <Button 
                      variant="ghost" 
                      size="sm" 
                      class="w-full justify-start text-xs h-6"
                      @click="add_component_to_structure(structure.ref, 'water')"
                    >
                      {{ t('molstar.structureTree.water') }}
                    </Button>
                    <Button 
                      variant="ghost" 
                      size="sm" 
                      class="w-full justify-start text-xs h-6"
                      @click="add_component_to_structure(structure.ref, 'ion')"
                    >
                      {{ t('molstar.structureTree.ion') }}
                    </Button>
                  </div>
                </PopoverContent>
              </Popover>
            </div>
            
            <!-- Components List (Collapsible) -->
            <div v-if="!is_structure_collapsed(structure.ref)" class="space-y-1">
              <div v-for="component in structure.components" :key="component.ref" class="space-y-1 p-2 rounded border bg-muted/30">
                <!-- Component Header -->
                <div class="flex items-center justify-between gap-1">
                  <div class="text-xs font-medium flex-1 truncate">
                    {{ component.label }}
                  </div>
                  <div class="flex items-center gap-1">
                    <!-- Add Representation -->
                    <Popover>
                      <PopoverTrigger as-child>
                        <Button
                          size="sm"
                          variant="ghost"
                          class="h-5 px-0 text-xs"
                        >
                          <Plus class="h-3 w-3" />
                        </Button>
                      </PopoverTrigger>
                      <PopoverContent class="w-48" side="left">
                        <div class="space-y-2">
                          <h5 class="font-medium text-xs">{{ t('molstar.structureTree.addRepresentation') }}</h5>
                          <div class="space-y-1">
                            <Button 
                              variant="ghost" 
                              size="sm" 
                              class="w-full justify-start text-xs"
                              @click="add_repr(component.ref, 'cartoon')"
                            >
                              cartoon
                            </Button>
                            <Button 
                              variant="ghost" 
                              size="sm" 
                              class="w-full justify-start text-xs"
                              @click="add_repr(component.ref, 'ball-and-stick')"
                            >
                              ball-and-stick
                            </Button>
                            <Button 
                              variant="ghost" 
                              size="sm" 
                              class="w-full justify-start text-xs"
                              @click="add_repr(component.ref, 'spacefill')"
                            >
                              spacefill
                            </Button>
                            <Button 
                              variant="ghost" 
                              size="sm" 
                              class="w-full justify-start text-xs"
                              @click="add_repr(component.ref, 'line')"
                            >
                              line
                            </Button>
                            <Button 
                              variant="ghost" 
                              size="sm" 
                              class="w-full justify-start text-xs"
                              @click="add_repr(component.ref, 'gaussian-surface')"
                            >
                              surface
                            </Button>
                            <Button 
                              variant="ghost" 
                              size="sm" 
                              class="w-full justify-start text-xs"
                              @click="add_repr(component.ref, 'label')"
                            >
                              label
                            </Button>
                          </div>
                        </div>
                      </PopoverContent>
                    </Popover>
                    
                    <!-- Delete Component -->
                    <Button
                      size="sm"
                      variant="ghost"
                      class="h-5 w-5 p-0 text-destructive hover:text-destructive"
                      @click="delete_component_from_structure(component.ref)"
                    >
                      <Trash2 class="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              
                <!-- Representations -->
                <div v-for="repr in component.representations" :key="repr.ref" class="space-y-1 ml-2">
                  <div class="flex items-center gap-2 p-1 rounded hover:bg-accent">
                    <Button
                      size="sm"
                      variant="ghost"
                      class="h-6 w-6 p-0"
                      @click="toggle_repr_visibility(repr.ref)"
                    >
                      <Eye v-if="repr.visible" class="h-3 w-3" />
                      <EyeOff v-else class="h-3 w-3" />
                    </Button>
                    
                    <span class="text-xs flex-1 truncate">
                      {{ repr.type }}
                    </span>
                    
                    <Popover>
                      <PopoverTrigger as-child>
                        <Button
                          size="sm"
                          variant="ghost"
                          class="h-6 w-6 p-0"
                        >
                          <Settings class="h-3 w-3" />
                        </Button>
                      </PopoverTrigger>
                      <PopoverContent class="w-56" side="left">
                        <div class="space-y-3">
                          <h5 class="font-medium text-xs">{{ t('molstar.structureTree.editRepresentation') }}</h5>
                          <!-- Alpha (Transparency) -->
                          <div class="space-y-1">
                            <Label class="text-xs">{{ t('molstar.structureTree.transparency') }}</Label>
                            <div class="flex items-center gap-2">
                              <Input 
                                type="number" 
                                :min=0
                                :max=1 
                                :step=0.1 
                                :model-value="repr.params?.type?.params?.alpha ?? 1"
                                class="h-7 text-xs"
                                @change="(e) => change_repr_alpha(repr.ref, parseFloat(e.target.value))"
                              />
                            </div>
                          </div>
                          
                          <!-- Color Theme -->
                          <div class="space-y-1">
                            <Label class="text-xs">{{ t('molstar.structureTree.color') }}</Label>
                            <RadioGroup 
                              :model-value="repr.params?.color || repr.params?.colorTheme?.name || 'element-symbol'"
                              @update:model-value="(val) => change_repr_color(repr.ref, val)"
                              class="space-y-1"
                            >
                              <div class="flex items-center space-x-2">
                                <RadioGroupItem :id="`${repr.ref}-element-symbol`" value="element-symbol" />
                                <Label :for="`${repr.ref}-element-symbol`" class="text-xs cursor-pointer">{{ t('molstar.structureTree.elementSymbol') }}</Label>
                              </div>
                              <div class="flex items-center space-x-2">
                                <RadioGroupItem :id="`${repr.ref}-chain-id`" value="chain-id" />
                                <Label :for="`${repr.ref}-chain-id`" class="text-xs cursor-pointer">{{ t('molstar.structureTree.chainId') }}</Label>
                              </div>
                              <div class="flex items-center space-x-2">
                                <RadioGroupItem :id="`${repr.ref}-uniform`" value="uniform" />
                                <Label :for="`${repr.ref}-uniform`" class="text-xs cursor-pointer">{{ t('molstar.structureTree.uniform') }}</Label>
                              </div>
                              <div class="flex items-center space-x-2">
                                <RadioGroupItem :id="`${repr.ref}-hydrophobicity`" value="hydrophobicity" />
                                <Label :for="`${repr.ref}-hydrophobicity`" class="text-xs cursor-pointer">{{ t('molstar.structureTree.hydrophobicity') }}</Label>
                              </div>
                            </RadioGroup>
                          </div>
                          
                          <Separator />
                          
                          <!-- Delete -->
                          <Button
                            size="sm"
                            variant="destructive"
                            class="w-full text-xs"
                            @click="delete_repr(repr.ref)"
                          >
                            {{ t('molstar.structureTree.deleteRepresentation') }}
                          </Button>
                        </div>
                      </PopoverContent>
                    </Popover>
                    
                    <Button
                      size="sm"
                      variant="ghost"
                      class="h-6 w-6 p-0 text-destructive hover:text-destructive"
                      @click="delete_repr(repr.ref)"
                    >
                      <Trash2 class="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              </div>
              
              <!-- Contacts Group -->
              <div v-if="structure.contacts && structure.contacts.length > 0" class="space-y-1 mt-2">
                <div class="p-2 rounded border bg-blue-50/30 dark:bg-blue-950/30">
                  <div class="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="ghost"
                      class="h-6 w-6 p-0"
                      @click="toggle_all_contacts_visibility(structure.ref, structure.contacts)"
                    >
                      <Eye v-if="are_all_contacts_visible(structure.contacts)" class="h-3 w-3" />
                      <EyeOff v-else class="h-3 w-3" />
                    </Button>
                    <span class="text-xs flex-1 font-medium">
                      Interactions ({{ structure.contacts.length }})
                    </span>
                    <Button
                      size="sm"
                      variant="ghost"
                      class="h-6 w-6 p-0 text-destructive hover:text-destructive"
                      @click="delete_all_contacts(structure.ref, structure.contacts)"
                    >
                      <Trash2 class="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </ScrollArea>
    </div>
  </div>
</template>

<script setup>
  import { ref, onMounted, onBeforeUnmount, nextTick, computed, watch } from 'vue'
  import { useI18n } from 'vue-i18n'
  import interaction_2d_viewer from '@/components/molecule/interaction_2d_viewer.vue'
  import { toast } from '@/components/ui/toast/use-toast'
  import { Button } from '@/components/ui/button'
  import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
  import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
  import { 
    AlertDialog,
    AlertDialogAction,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
  } from '@/components/ui/alert-dialog'
  import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
  import { Checkbox } from '@/components/ui/checkbox'
  import { Input } from '@/components/ui/input'
  import { Label } from '@/components/ui/label'
  import { Separator } from '@/components/ui/separator'
  import { ScrollArea } from '@/components/ui/scroll-area'
  import { 
    DropdownMenu, 
    DropdownMenuContent, 
    DropdownMenuItem, 
    DropdownMenuTrigger 
  } from '@/components/ui/dropdown-menu'
  import { 
    Edit, Trash2, Eye, EyeOff, Settings, 
    Share2, Camera, ScanEye, Network,
    SquareDashedMousePointer, Rotate3D,
    Fullscreen, ChevronDown, ChevronRight,
    Plus
  } from 'lucide-vue-next'
  import { cn } from '@/lib/utils'
  import 'drugflow-molstar/build/drugflow-molstar-0.4.11.css'
  import 'drugflow-molstar/build/drugflow-molstar-component-0.4.11.js'
  import { Queries, StructureQuery, StructureSelection, StructureProperties, StructureElement } from 'molstar/lib/mol-model/structure'
  import { InteractionsRepresentationProvider } from 'molstar/lib/mol-model-props/computed/representations/interactions'
  import { setSubtreeVisibility } from 'molstar/lib/mol-plugin/behavior/static/state'
  import { Vec3 } from 'molstar/lib/mol-math/linear-algebra'
  import { Color, ColorMap } from 'molstar/lib/mol-util/color';
  import { ColorNames } from 'molstar/lib/mol-util/color/names';
  
  const { t } = useI18n()
  
  const molstar_ref = ref(null)
  const canvas_id = 'molstar-canvas-' + Date.now()
  const full_screen_type = ref(false)
  const granularity = ref('residue')
  const background = ref('white')
  const expand_number = ref(5)
  const pdb_info = ref({'chain': [], 'ligand': [], 'pocket': [], 'other': [], 'water': []})
  const show_tool = ref(true)
  const init_params = ref({})
  const show_prolif = ref(false)
  const pdb_ligand_inter_list = ref([])
  const wait_proif = ref(true)
  const prolif_data = ref([])
  const structure_tree = ref([])
  const ligand_list_for_2d = ref([])
  const structure_tree_open = ref(true)
  const selection_tools_open = ref(false)
  const collapsed_structures = ref(new Set())
  const structure_visibility = ref(new Map())
  const has_selection = ref(false)
  const new_component_name = ref('')
  const structure_label_map = ref(new Map()) // 存储 structureRef -> customLabel 的映射
  const structure_color_map = ref(new Map()) // 存储 structureRef -> color 的映射
  const webgl_error_dialog = ref(false)

  const props = defineProps({
    interaction_2d: { type: Object, default: null },
    ligand_only: { type: Boolean, default: false },
    box_bg_color: {
      type: Number,
      default: 0x1100CC
    },
    dark_background: {
      type: Boolean,
      default: true
    },
    if_sequence_panel: {
      type: Boolean,
      default: true
    },
    show_tool: {
      type: Boolean,
      default: true
    },
    init_show_tree: {
      type: Boolean,
      default: true
    },
    prolif_show_ligname: {
      type: Boolean,
      default: true
    },
    ligand_view_mode: {
      type: String,
      default: 'pocket'
    },
  })
  const emit = defineEmits(['init-complete', 'request-2d', 'residue-select']);

  const init = async() => {
    const instance = new DrugflowMolstarPlugin()
    molstar_ref.value.viewerInstance = instance
    let viewerContainer = document.getElementById(canvas_id);
    console.log('init!!!!viewerContainer', viewerContainer)
    await instance.init(
      viewerContainer,
      {'if_sequence_panel': props.if_sequence_panel}
    )
    if (disposed) return
    // Without graphics support the library finishes setup without a 3D canvas instead of throwing.
    if (!instance.plugin?.canvas3d) throw new Error('3D canvas could not be created')
    resizeObserver = new ResizeObserver(() => instance.plugin.handleResize())
    resizeObserver.observe(viewerContainer)
    instance.canvas.toggleSelect(false)
    molstar_ref.value.viewerInstance.add_click_listener()
    
    // 添加选择变化监听器
    add_selection_listener()
  }

  let initialization = Promise.resolve()
  let sceneQueue = Promise.resolve()
  let disposed = false
  let resizeObserver
  const overlays = new Map()
  const enqueueScene = (action) => {
    const next = sceneQueue.then(() => { if (!disposed) return action() })
    sceneQueue = next.catch(() => {})
    return next
  }
  onBeforeUnmount(() => {
    disposed = true
    resizeObserver?.disconnect()
    const instance = molstar_ref.value?.viewerInstance
    void Promise.allSettled([initialization, sceneQueue]).then(() => instance?.plugin?.dispose())
  })
  const load_structure = (params) => enqueueScene(() => loadStructureNow(params))
  const loadStructureNow = async(input_params) => {
    init_params.value = input_params
    const render_id = input_params.render_id
    
    let actualStructureId = '0' // 默认值
    
    // 🔹 使用新的加载API，并获取实际的结构ID
    if (input_params.render_type === 'default') {
      overlays.clear()
      ligand_list_for_2d.value = []
      structure_label_map.value.clear()
      structure_color_map.value.clear()
      // 使用 loadFullProtein
      const result = await molstar_ref.value.viewerInstance.loadFullProtein(
        input_params.url || '',
        input_params.format || 'pdb',
        {
          isBinary: input_params.is_binary,
          pdbString: input_params.input,
          showPolymer: true,
          showLigand: true,
          showWater: true
        }
      )
      actualStructureId = result.structureId
      const plugin = molstar_ref.value.viewerInstance.plugin
      const ligand = plugin.state.data.select('Ligand')[0]
      if (ligand?.obj?.data) {
        const selection = StructureQuery.run(Queries.generators.atoms({
          residueTest: ({ element }) => StructureProperties.atom.label_comp_id(element) !== 'PTR',
        }), ligand.obj.data)
        const loci = StructureElement.Loci.remap(StructureSelection.toLociWithSourceUnits(selection),
          plugin.state.data.select('Structure_' + actualStructureId)[0].obj.data)
        await plugin.build().to(ligand.transform.ref).update({
          type: { name: 'bundle', params: StructureElement.Bundle.fromLoci(loci) },
          nullIfEmpty: true, label: ligand.obj.label,
        }).commit()
      }
    } else if (input_params.render_type === 'ligand_view') {
      // 使用 loadLigandPocket
      console.log('input_params', input_params)
      const result = await molstar_ref.value.viewerInstance.loadLigandPocket(
        input_params.url || '',
        {
          name: input_params.ligand_name,
          site: input_params.ligand_site,
          ligandId: render_id
        },
        input_params.format || 'pdb',
        {
          isBinary: input_params.is_binary,
          pdbString: input_params.input,
          clearPrevious: input_params.if_clean !== false, // 默认true，但允许false来叠加显示
          radius: 5
        }
      )
      actualStructureId = result.structureId
      
      // 记录配体信息用于2D相互作用查看
      // 解析 ligand_site 来获取 chain_id 和 residue_number
      // ligand_site 格式通常是 "A:301" 或类似
      let chainId = ''
      let residueNumber = ''
      if (input_params.ligand_site) {
        const parts = input_params.ligand_site.split(':')
        if (parts.length >= 2) {
          chainId = parts[0]
          residueNumber = parts[1]
        }
      }
      
      // 添加到配体列表
      // if (input_params.if_clean) {
        // ligand_list_for_2d.value = [] // 清空之前的配体列表
      // }
      
      // 为参考配体生成特殊标签
      let ligandLabel = input_params.structure_label || input_params.pdb_name || render_id
      if (render_id === '0' || render_id === 0) {
        // 参考配体，添加前缀标识
        ligandLabel = t('result.参考配体') + (input_params.structure_label ? ` (${input_params.structure_label})` : '')
      }
      
      ligand_list_for_2d.value.push({
        componentRef: 'Ligand_' + render_id, // 使用纯配体组件，不包含周围环境
        componentRefWithPocket: 'Ligand_plus_' + render_id, // 配体加周围环境，用于相互作用计算
        structureId: actualStructureId,
        label: ligandLabel,
        chainId: chainId,
        residueName: input_params.ligand_name || 'UNL',
        residueNumber: residueNumber,
        renderId: render_id,
        ligandSmiles: input_params.ligand_smiles || '',
        mol_block: input_params.mol_block || '',
        isReference: render_id === '0' || render_id === 0 // 标记是否为参考配体
      })
      
      console.log(`✅ Added ligand to 2D interaction list: ${ligandLabel} (render_id: ${render_id})`)
    } else if (input_params.render_type === 'peptide' || input_params.render_type === 'peptide_background') {
      // 使用 loadPeptide
      const result = await molstar_ref.value.viewerInstance.loadPeptide(
        input_params.url,
        input_params.format || 'pdb',
        {
          isBinary: input_params.is_binary,
          pdbString: input_params.input,
          showBackground: input_params.render_type === 'peptide_background',
          showLigand: false,
          showWater: false,
          peptideId: render_id, // 传递肽链ID用于组件命名
          clearPrevious: input_params.if_clean !== false // 是否清空之前的内容
        }
      )
      actualStructureId = result.structureId
    }
    
    // 保存自定义结构标签（使用实际的结构ID）
    if (input_params.structure_label) {
      structure_label_map.value.set('Structure_' + actualStructureId, input_params.structure_label)
    }
    
    // 保存配体颜色（使用实际的结构ID）
    if (input_params.carbon_color) {
      structure_color_map.value.set('Structure_' + actualStructureId, input_params.carbon_color)
    }
    
    // 保存 render_id 到实际 structureId 的映射
    if (render_id !== actualStructureId) {
      console.log(`🔄 Mapping render_id ${render_id} -> actualStructureId ${actualStructureId}`)
    }
    
    try {
      const structureRef = actualStructureId !== undefined ? 'Structure_' + actualStructureId : undefined
      pdb_info.value = molstar_ref.value.viewerInstance.get_basic_info(structureRef)
    } catch (error) {
      console.error('Failed to get basic info:', error)
    }
    
    // 🔹 添加表示（使用新的 add_repr API）
    if (input_params.render_type === 'default') {
      if (input_params.format === 'sdf') {
        await add_or_update_sdf_repr()
      } else {
        await add_or_update_default_repr(1, true, false)
      }
    } else if (input_params.render_type === 'peptide_background') {
      await add_or_update_peptide_background_repr(input_params.carbon_color)
    } else if (input_params.render_type === 'peptide') {
      await add_or_update_peptide_repr(render_id, input_params.peptide_chain_name, input_params.carbon_color)
    } else if (input_params.render_type === 'ligand_view') {
      // 使用实际的结构ID
      await add_or_update_ligand_view_repr(
        render_id,
        input_params.carbon_color,
        actualStructureId,
        input_params.ligand_view_mode || props.ligand_view_mode
      )
    }
    
    if (input_params.if_clean) {
      pdb_ligand_inter_list.value = []
      // ligand_list_for_2d.value = []
    } 
    if (input_params.only_display) {
      // Refresh structure tree even for display-only loads
      refresh_structure_tree()
      return actualStructureId
    }

    // Handle initial visibility setting
    if (input_params.initial_visible === false && input_params.render_type === 'ligand_view') {
      // Refresh structure tree to ensure we have the latest structure
      refresh_structure_tree()
      
      // 使用实际的结构ID
      const structureRef = 'Structure_' + actualStructureId
      // Set initial visibility to false
      structure_visibility.value.set(structureRef, false)
      // Hide the structure by toggling all its representations
      const structure = structure_tree.value.find(s => s.ref === structureRef)
      if (structure) {
        for (const component of structure.components) {
          for (const repr of component.representations) {
            const reprCell = molstar_ref.value.viewerInstance.plugin.state.data.cells.get(repr.ref)
            if (reprCell && !reprCell.state.isHidden) {
              await molstar_ref.value.viewerInstance.toggleRepresentationVisibility(repr.ref)
            }
          }
        }
      }
    }
    
    // 使用 molstar 自带的相互作用绘制（不再需要后端 prolif 数据）
    const is_ligand_view = input_params.render_type !== 'default' && input_params.render_type !== 'peptide' && input_params.render_type !== 'peptide_background'
    
    wait_proif.value = false
    
    if (is_ligand_view) {
      // 使用 molstar 自带的相互作用绘制（类似 peptide 的方式）
      // ligand 使用 Ligand_plus_[render_id] 组件来绘制 interaction
      const componentRef = 'Ligand_plus_' + render_id
      await molstar_ref.value.viewerInstance.show_component_interactions(
        componentRef,
        actualStructureId,
        ['hydrogen-bond', 'hydrophobic', 'pi-stacking', 'cation-pi', 'ionic', 'halogen-bond'],
        true
      )
      console.log(`✅ Added interactions for ${componentRef}`)
    }
    
    // Refresh structure tree after loading
    refresh_structure_tree()
    
    // 返回实际使用的结构ID
    return actualStructureId
  }

  // Independent files retain their coordinates and never enter the interaction calculator.
  const load_overlay = (input, format = 'sdf', id = 'reference', color = 0xf59e0b, pocket = false, focus = pocket) => enqueueScene(async () => {
    const plugin = molstar_ref.value.viewerInstance.plugin
    const previous = overlays.get(id)
    if (previous) {
      const update = plugin.build().delete(previous.data.ref)
      if (previous.pocket) update.delete(previous.pocket.ref)
      await update.commit()
      overlays.delete(id)
    }
    if (!input) { refresh_structure_tree(); return }
    const data = await plugin.builders.data.rawData({ data: input, label: id })
    let pocketComponent
    try {
      const trajectory = await plugin.builders.structure.parseTrajectory(data, format)
      const model = await plugin.builders.structure.createModel(trajectory)
      const structure = await plugin.builders.structure.createStructure(model, { name: 'model', params: {} })
      const component = await plugin.builders.structure.tryCreateComponentStatic(structure, 'all', { label: id })
      if (!component || !structure.obj?.data.elementCount) throw new Error('Empty ligand structure')
      await plugin.builders.structure.representation.addRepresentation(component, {
        type: 'ball-and-stick', color: 'element-symbol',
        colorParams: { carbonColor: { name: 'uniform', params: { value: color } } },
        typeParams: { ignoreHydrogens: true },
      })
      const receptor = plugin.state.data.select('Structure_0')[0]?.obj?.data
      if (pocket && receptor) {
        const residues = new Set()
        const position = Vec3()
        const location = StructureElement.Location.create(receptor)
        const residueKey = (loc) => `${loc.unit.id}:${StructureProperties.residue.key(loc)}`
        for (const unit of structure.obj.data.units) {
          for (const element of unit.elements) {
            if (unit.model.atomicHierarchy.atoms.type_symbol.value(element) === 'H') continue
            unit.conformation.position(element, position)
            const nearby = receptor.lookup3d.find(...position, 5)
            for (let i = 0; i < nearby.count; i++) {
              location.unit = nearby.units[i]
              location.element = location.unit.elements[nearby.indices[i]]
              if (StructureProperties.entity.type(location) === 'polymer'
                && StructureProperties.atom.type_symbol(location) !== 'H') residues.add(residueKey(location))
            }
          }
        }
        const selection = StructureQuery.run(Queries.generators.atoms({
          residueTest: ({ element }) => residues.has(residueKey(element)),
        }), receptor)
        const loci = StructureSelection.toLociWithSourceUnits(selection)
        pocketComponent = await plugin.builders.structure.tryCreateComponent('Structure_0', {
          type: { name: 'bundle', params: StructureElement.Bundle.fromLoci(loci) },
          nullIfEmpty: true, label: 'Pocket (5 Å)',
        }, `binding-pocket-${id}`)
        if (pocketComponent) await plugin.builders.structure.representation.addRepresentation(pocketComponent, {
          type: 'ball-and-stick', color: 'element-symbol', typeParams: { ignoreHydrogens: true, sizeFactor: 0.15 },
        })
      }
      overlays.set(id, { data, structure, pocket: pocketComponent })
      if (focus) plugin.managers.camera.focusLoci(StructureElement.Loci.all(structure.obj.data), { extraRadius: 5 })
      refresh_structure_tree()
      const coordinates = []
      const position = Vec3()
      for (const unit of structure.obj.data.units) {
        for (const element of unit.elements) {
          if (['H', 'D'].includes(unit.model.atomicHierarchy.atoms.type_symbol.value(element))) continue
          unit.conformation.position(element, position)
          coordinates.push([...position])
        }
      }
      return coordinates
    } catch (error) {
      const update = plugin.build().delete(data.ref)
      if (pocketComponent) update.delete(pocketComponent.ref)
      await update.commit()
      throw error
    }
  })
  const set_overlay_visible = (id, visible) => enqueueScene(() => {
    const plugin = molstar_ref.value.viewerInstance.plugin
    const overlay = overlays.get(id)
    if (overlay) {
      setSubtreeVisibility(plugin.state.data, overlay.data.ref, !visible)
      if (overlay.pocket) setSubtreeVisibility(plugin.state.data, overlay.pocket.ref, !visible)
    }
  })
  const get_overlay_id = (loci) => {
    for (const [id, overlay] of overlays) {
      if (overlay.structure.obj.data.root === loci.structure.root) return id
    }
  }

  const clear_structure = () => enqueueScene(async () => {
    await molstar_ref.value.viewerInstance.clear()
    overlays.clear()
    ligand_list_for_2d.value = []
    structure_label_map.value.clear()
    structure_color_map.value.clear()
  })

  const set_occlusion = () => {
    molstar_ref.value.viewerInstance.plugin.canvas3d.setProps({
        postprocessing: { occlusion: { name: 'off', params: {} } }
    });
  }

  const add_full_protein_backbone_repr = async (ligand_id, structure_id, alpha = 0.1) => {
    const polymerComponentRef = await molstar_ref.value.viewerInstance.createComponent({
      type: 'polymer',
      structureId: structure_id,
      label: `Protein ${ligand_id}`
    })

    if (!polymerComponentRef) return

    await molstar_ref.value.viewerInstance.add_repr({
      componentRef: polymerComponentRef,
      reprRef: `${polymerComponentRef}_cartoon`,
      type: 'cartoon',
      colorTheme: 'chain-id',
      alpha,
      visible: true,
      structureId: structure_id
    })
  }

  const add_or_update_ligand_view_repr = async(ligand_id, color_name, structure_id, ligand_view_mode = 'pocket') => {
    // 当未指定structure_id时，默认使用ligand_id（用于多配体叠加）
    // 参考配体使用'0'
    const actual_structure_id = structure_id !== undefined ? structure_id : (ligand_id === '0' ? '0' : ligand_id)
    if (ligand_view_mode === 'full-protein') {
      await add_full_protein_backbone_repr(ligand_id, actual_structure_id, 0.1)
    } else if (ligand_id === '0') {
      await molstar_ref.value.viewerInstance.add_repr({
        componentRef: 'Ligand_background',
        reprRef: 'Ligand_Background_cartoon',
        type: 'cartoon',
        alpha: 0.1,
        visible: true
      })
    }

    // 🔹 使用新的 add_repr API - Ligand
    await molstar_ref.value.viewerInstance.add_repr({
      componentRef: 'Ligand_' + ligand_id,
      reprRef: 'Ligand_' + ligand_id + '_bs',
      type: 'ball-and-stick',
      colorTheme: 'element-symbol',
      alpha: 1,
      visible: true,
      structureId: actual_structure_id,
      params: {
        typeParams: {
          ignoreHydrogens: 'all', 
          ignoreHydrogensVariant: 'non-polar'
        },
        colorParams: { 
          carbonColor: {name: 'element-symbol', params: {}}, 
          colors: { name: 'custom', params: ColorMap({'C': ColorNames[color_name]})}
        }
      }
    })
    
    // 🔹 使用新的 add_repr API - Ligand_plus line
    await molstar_ref.value.viewerInstance.add_repr({
      componentRef: 'Ligand_plus_' + ligand_id,
      reprRef: 'Ligand_plus_' + ligand_id + '_line',
      type: 'line',
      alpha: 0.3,
      visible: true,
      structureId: actual_structure_id,
      params: {
        typeParams: { 
          ignoreHydrogens: 'all', 
          ignoreHydrogensVariant: 'non-polar' 
        },
        colorParams: { 
          carbonColor: {name: 'element-symbol', params: {}}, 
          colors: { name: 'custom', params: ColorMap({'C': ColorNames.gray})}
        }
      }
    })
    
    // 🔹 使用新的 add_repr API - Ligand_plus label
    await molstar_ref.value.viewerInstance.add_repr({
      componentRef: 'Ligand_plus_' + ligand_id,
      reprRef: 'Ligand_plus_' + ligand_id + '_label',
      type: 'label',
      alpha: 0.5,
      visible: true,
      structureId: actual_structure_id,
      params: {
        sizeParams: { scale: 0.65 },
        colorParams: { value: 0xffffff },
        typeParams: { level: granularity.value }
      }
    })
    
    // focus ligand (UNL center)
    const structureRef = 'Structure_' + actual_structure_id
    const ligandInfo = molstar_ref.value.viewerInstance.get_basic_info(structureRef)
    for (let i = 0; i < ligandInfo.ligand.length; i++) {
      if (ligandInfo.ligand[i].residue_name === 'UNL') {
        molstar_ref.value.viewerInstance.visual.focus([ligandInfo.ligand[i]], undefined, 10, structureRef)
        break
      }
    }
    set_occlusion()
  }

  const add_or_update_default_repr = async (alpha=1, if_hetatm=true, not_change_visible=true) => {
    // 🔹 使用新的 add_repr API
    await molstar_ref.value.viewerInstance.add_repr({
      componentRef: 'Polymer',
      reprRef: 'Polymer_cartoon',
      type: 'cartoon',
      alpha: alpha,
      visible: true
    })
    
    if (if_hetatm) {
      if (pdb_info.value.ligand.length > 0) {
        await molstar_ref.value.viewerInstance.add_repr({
          componentRef: 'Ligand',
          reprRef: 'Ligand_bs',
          type: 'ball-and-stick',
          colorTheme: 'element-symbol',
          visible: true,
          params: {
            typeParams: {
              ignoreHydrogens: 'all', 
              ignoreHydrogensVariant: 'non-polar'
            },
            colorParams: { 
              carbonColor: {name: 'element-symbol', params: {}}, 
              colors: { name: 'custom', params: ColorMap({'C': ColorNames.orange})}
            }
          }
        })
      }
      if (pdb_info.value.water.length > 0) {
        await molstar_ref.value.viewerInstance.add_repr({
          componentRef: 'Water',
          reprRef: 'Water_bs',
          type: 'ball-and-stick',
          visible: true
        })
      }
    }
    set_occlusion()
  }

  const add_or_update_sdf_repr = async () => {
    // 🔹 使用新的 add_repr API
    await molstar_ref.value.viewerInstance.add_repr({
      componentRef: 'Ligand',
      reprRef: 'Ligand_bs',
      type: 'ball-and-stick',
      colorTheme: 'element-symbol',
      visible: true,
      params: {
        typeParams: {
          ignoreHydrogens: 'all', 
          ignoreHydrogensVariant: 'non-polar'
        },
        colorParams: { 
          carbonColor: {name: 'element-symbol', params: {}}, 
          colors: { name: 'custom', params: ColorMap({'C': ColorNames.orange})}
        }
      }
    })
  }

  const add_or_update_peptide_background_repr = async (color_name='red') => {
    // 🔹 使用新的 add_repr API - Polymer_p_background (背景蛋白) cartoon
    await molstar_ref.value.viewerInstance.add_repr({
      componentRef: 'Polymer_p_background',
      reprRef: 'Polymer_p_background_cartoon',
      type: 'cartoon',
      alpha: 0.1,
      visible: true
    })

    // 🔹 使用新的 add_repr API - Polymer_p_background_peptide (肽链) cartoon
    await molstar_ref.value.viewerInstance.add_repr({
      componentRef: 'Polymer_p_background_peptide',
      reprRef: 'Polymer_p_background_peptide_cartoon',
      type: 'cartoon',
      colorTheme: 'uniform',
      alpha: 0.3,
      visible: true,
      params: {
        colorParams: {
          value: ColorNames[color_name]
        }
      }
    })
    
    // 🔹 使用新的 add_repr API - Polymer_p_background_peptide ball-and-stick
    await molstar_ref.value.viewerInstance.add_repr({
      componentRef: 'Polymer_p_background_peptide',
      reprRef: 'Polymer_p_background_peptide_bs',
      type: 'ball-and-stick',
      colorTheme: 'element-symbol',
      alpha: 1,
      visible: true,
      params: {
        sizeParams: { value: 0.9 },
        typeParams: {
          ignoreHydrogens: 'all', 
          ignoreHydrogensVariant: 'non-polar'
        },
        colorParams: { 
          carbonColor: {name: 'element-symbol', params: {}}, 
          colors: { name: 'custom', params: ColorMap({'C': ColorNames[color_name]})}
        }
      }
    })

    // 🔹 创建背景肽链的周围环境组件并添加相互作用
    await create_peptide_background_surroundings_component(color_name)
  }

  /**
   * 创建背景肽链的周围环境组件并计算相互作用
   * 用于计算背景肽链与背景蛋白之间的相互作用
   */
  const create_peptide_background_surroundings_component = async (color_name = 'red') => {
    try {
      const structureId = '0' // peptide_background 使用 'Original' 作为 structureId
      
      // 调用底层 API 创建周围环境组件
      await molstar_ref.value.viewerInstance.create_peptide_background_surroundings_component({
        structureId: structureId,
        radius: 5
      })
      
      console.log(`✅ Created surroundings component for peptide_background`)
      
      // 为周围环境组件添加相互作用表示
      const componentRef = `Polymer_p_background_plus`
      
      // 使用映射后的 structureId（Original -> 0）
      const actualStructureId = '0'

      // 🔹 添加 Polymer_p_background_plus line 表示
      await molstar_ref.value.viewerInstance.add_repr({
        componentRef: componentRef,
        reprRef: `${componentRef}_line`,
        type: 'line',
        alpha: 0.3,
        visible: true,
        structureId: actualStructureId,
        params: {
          typeParams: {
            ignoreHydrogens: 'all',
            ignoreHydrogensVariant: 'non-polar'
          },
          colorParams: {
            carbonColor: {name: 'element-symbol', params: {}},
            colors: {name: 'custom', params: ColorMap({'C': ColorNames.gray})}
          }
        }
      })

      // 🔹 添加 Polymer_p_background_plus label 表示
      await molstar_ref.value.viewerInstance.add_repr({
        componentRef: componentRef,
        reprRef: `${componentRef}_label`,
        type: 'label',
        alpha: 0.5,
        visible: true,
        structureId: actualStructureId,
        params: {
          sizeParams: { scale: 0.65 },
          colorParams: { value: 0xffffff },
          typeParams: { level: granularity.value }
        }
      })
      
      console.log(`✅ Added line and label for ${componentRef}`)
      
      // 🔹 添加相互作用表示
      const reprRef = await molstar_ref.value.viewerInstance.show_component_interactions(
        componentRef,
        actualStructureId
      )
      
      console.log(`✅ Added interactions for ${componentRef}`)
    } catch (error) {
      console.error(`Failed to create surroundings and interactions for peptide_background:`, error)
      // 不抛出错误，因为这是可选的
    }
  }

  const add_or_update_peptide_repr = async (peptide_id, peptide_chain_name, color_name='gray') => {
    // 🔹 使用新的 add_repr API - Polymer_p cartoon
    await molstar_ref.value.viewerInstance.add_repr({
      componentRef: 'Polymer_p' + peptide_id,
      reprRef: 'Polymer_cartoon' + peptide_id,
      type: 'cartoon',
      colorTheme: 'uniform',
      alpha: 0.3,
      visible: true,
      params: {
        colorParams: {
          value: ColorNames[color_name]
        }
      }
    })
    
    // 🔹 使用新的 add_repr API - Polymer_p ball-and-stick
    await molstar_ref.value.viewerInstance.add_repr({
      componentRef: 'Polymer_p' + peptide_id,
      reprRef: 'Polymer_bs' + peptide_id,
      type: 'ball-and-stick',
      colorTheme: 'element-symbol',
      alpha: 1,
      visible: true,
      params: {
        sizeParams: { value: 0.9 },
        typeParams: {
          ignoreHydrogens: 'all', 
          ignoreHydrogensVariant: 'non-polar'
        },
        colorParams: { 
          carbonColor: {name: 'element-symbol', params: {}}, 
          colors: { name: 'custom', params: ColorMap({'C': ColorNames[color_name]})}
        }
      }
    })

    // 🔹 创建多肽周围环境组件（用于相互作用计算）
    await create_peptide_surroundings_component(peptide_id, peptide_chain_name)

    set_occlusion()
    
    // Focus on the peptide chain
    if (peptide_chain_name) {
      const peptide_chains = pdb_info.value.chain.filter(c => c.auth_asym_id === peptide_chain_name)
      if (peptide_chains.length > 0) {
        molstar_ref.value.viewerInstance.visual.focus(peptide_chains, undefined, 10)
      }
    }
  }

  /**
   * 创建多肽周围环境组件（类似配体的 Ligand_plus）
   * 用于计算多肽与周围残基的相互作用
   */
  const create_peptide_surroundings_component = async (peptide_id, peptide_chain_name, radius = 5) => {
    try {
      const structureId = peptide_id // 使用 peptide_id 作为 structureId
      
      // 调用底层 API 创建周围环境组件
      await molstar_ref.value.viewerInstance.create_peptide_surroundings_component({
        peptideId: peptide_id,
        peptideChainName: peptide_chain_name,
        structureId: structureId,
        radius: radius
      })
      
      console.log(`✅ Created surroundings component for peptide ${peptide_id}`)
      
      // 为周围环境组件添加 line 和 label 表示
      const componentRef = `Polymer_p_plus_${peptide_id}`
      
      // 添加 line 表示（透明度 0.3）
      await molstar_ref.value.viewerInstance.add_repr({
        componentRef: componentRef,
        reprRef: `${componentRef}_line`,
        type: 'line',
        alpha: 0.3,
        visible: true,
        structureId: structureId,
        params: {
          typeParams: {
            ignoreHydrogens: 'all',
            ignoreHydrogensVariant: 'non-polar'
          },
          colorParams: {
            carbonColor: {name: 'element-symbol', params: {}},
            colors: {name: 'custom', params: ColorMap({'C': ColorNames.gray})}
          }
        }
      })
      
      // 添加 label 表示（透明度 0.3）
      await molstar_ref.value.viewerInstance.add_repr({
        componentRef: componentRef,
        reprRef: `${componentRef}_label`,
        type: 'label',
        alpha: 0.5,
        visible: true,
        structureId: structureId,
        params: {
          sizeParams: { scale: 0.65 },
          colorParams: { value: 0xffffff },
          typeParams: { level: granularity.value }
        }
      })
      
      console.log(`✅ Added line and label representations for ${componentRef}`)
    } catch (error) {
      console.error(`Failed to create surroundings component for peptide ${peptide_id}:`, error)
      // 不抛出错误，因为这是可选的
    }
  }

  const set_peptide_view_id_visibility = async (peptide_id) => {
    await molstar_ref.value.viewerInstance.set_visibility('Polymer_p' + peptide_id)
  }

  const reset_all = async () => {
    await molstar_ref.value.viewerInstance.clear()
    ligand_list_for_2d.value = []
    await load_structure(init_params.value)
  }

  const add_mouse_event = (func) => {
    molstar_ref.value.viewerInstance.add_mouse_event(func)
  }

  const get_pdb_info = () => {
    return pdb_info.value
  }

  const add_shape = (params) => {
    const structure = molstar_ref.value.viewerInstance.plugin.state.data.select('Structure_0')[0]
    return molstar_ref.value.viewerInstance.add_shape(structure, params)
  }

  const remove_shape = (selector) => {
    molstar_ref.value.viewerInstance.remove_shape(selector)
  }

  const full_screen = () => {
    full_screen_type.value = !full_screen_type.value
    molstar_ref.value.viewerInstance.canvas.toggleExpanded(full_screen_type.value)
  }

  const reset_camera = () => {
    molstar_ref.value.viewerInstance.visual.camera_reset()
  }

  const make_screenshot = () => {
    const c = document.getElementsByTagName('canvas')[0]
    const base64Img = c.toDataURL('image/png')
    const a = document.createElement('a')
    a.download = 'Drugflow_Screenshot.png'
    a.href = base64Img
    a.click()
    a.remove()
  }

  const toggle_spin = () => {
    molstar_ref.value.viewerInstance.visual.toggleSpin()
  }

  const change_background = () => {
    if (background.value === 'white') {
      set_background({r: 255, g: 255, b: 255})
    } else {
      set_background({r: 0, g: 0, b: 0})
    }
  }

  const set_visibility = (ref) => {
    molstar_ref.value.viewerInstance.set_visibility(ref)
  }


  // Structure Tree Management Methods
  const refresh_structure_tree = () => {
    if (!molstar_ref.value?.viewerInstance) return
    try {
      structure_tree.value = molstar_ref.value.viewerInstance.getStructureTree()
      structure_tree.value.forEach(s => { 
        if (!structure_visibility.value.has(s.ref)) {
          structure_visibility.value.set(s.ref, true)
          // New structures default to collapsed
          collapsed_structures.value.add(s.ref)
        }
      })
    } catch (e) {
      console.error('❌ Failed to refresh structure tree:', e)
      structure_tree.value = []
    }
  }

  const toggle_structure_collapsed = (structureRef) => {
    if (collapsed_structures.value.has(structureRef)) {
      collapsed_structures.value.delete(structureRef)
    } else {
      collapsed_structures.value.add(structureRef)
    }
  }

  const is_structure_collapsed = (structureRef) => {
    return collapsed_structures.value.has(structureRef)
  }

  const toggle_structure_visibility = async (structureRef) => {
    const isVisible = structure_visibility.value.get(structureRef)
    structure_visibility.value.set(structureRef, !isVisible)
    
    // Toggle all components and representations visibility
    const structure = structure_tree.value.find(s => s.ref === structureRef)
    if (structure) {
      for (const component of structure.components) {
        for (const repr of component.representations) {
          const reprCell = molstar_ref.value.viewerInstance.plugin.state.data.cells.get(repr.ref)
          if (reprCell) {
            const shouldBeHidden = reprCell.state.isHidden === isVisible
            if (!shouldBeHidden) {
              await molstar_ref.value.viewerInstance.toggleRepresentationVisibility(repr.ref)
            }
          }
        }
      }
      
      // 同时切换该结构的所有 contacts 的可见性
      if (structure.contacts && structure.contacts.length > 0) {
        for (const contact of structure.contacts) {
          // 如果结构从可见变为隐藏，则隐藏 contact
          // 如果结构从隐藏变为可见，则显示 contact
          if (contact.visible === isVisible) {
            await molstar_ref.value.viewerInstance.toggleContactVisibility(contact.ref)
          }
        }
      }
    }
    refresh_structure_tree()
  }

  const add_component_to_structure = async (structureRef, componentType) => {
    if (!molstar_ref.value?.viewerInstance) return
    try {
      const structureIndex = structureRef.split('_')[1] || '0'
      await molstar_ref.value.viewerInstance.createComponent({
        type: componentType,
        structureId: structureIndex
      })
      refresh_structure_tree()
    } catch (e) {
      console.error('Failed to add component:', e)
    }
  }

  const delete_component_from_structure = async (componentRef) => {
    if (!molstar_ref.value?.viewerInstance) return
    try {
      await molstar_ref.value.viewerInstance.deleteComponent(componentRef)
      refresh_structure_tree()
    } catch (e) {
      console.error('Failed to delete component:', e)
    }
  }

  // Check if there is a current selection
  const check_selection = () => {
    if (!molstar_ref.value?.viewerInstance) {
      has_selection.value = false
      return
    }
    try {
      const sel = molstar_ref.value.viewerInstance.plugin.managers.structure.hierarchy.getStructuresWithSelection()
      has_selection.value = sel && sel.length > 0
    } catch (e) {
      console.error('Failed to check selection:', e)
      has_selection.value = false
    }
  }

  // 添加选择变化监听器
  const add_selection_listener = () => {
    if (!molstar_ref.value?.viewerInstance) return
    
    try {
      // 订阅选择管理器的选择变化事件
      const plugin = molstar_ref.value.viewerInstance.plugin
      
      plugin.managers.structure.selection.events.changed.subscribe(() => {
        check_selection()
        
        // 如果有选择且结构树关闭，自动打开结构树
        if (has_selection.value && !structure_tree_open.value) {
          structure_tree_open.value = true
        }
      })
    } catch (e) {
      console.error('Failed to add selection listener:', e)
    }
  }

  // Create component from current selection with specific representation
  const create_component_from_selection = async (reprType) => {
    if (!molstar_ref.value?.viewerInstance || !has_selection.value) return
    
    try {
      const componentName = new_component_name.value.trim() || 'Selection'
      
      // 1. Get selection expression
      const expression = await molstar_ref.value.viewerInstance.getSelectionExpression()
      if (!expression) {
        console.warn('No selection found')
        has_selection.value = false
        return
      }
      
      // 2. Create component from expression
      const componentRef = await molstar_ref.value.viewerInstance.createComponent({
        type: 'custom',
        componentRef: `${componentName}_${Date.now()}`,
        structureId: '0',
        expression,
        label: componentName
      })
      
      if (!componentRef) {
        console.error('Failed to create component from selection')
        return
      }
      
      // 3. Add the specified representation (注意：add_repr 接受对象参数)
      await molstar_ref.value.viewerInstance.add_repr({
        componentRef: componentRef,
        type: reprType,
        colorTheme: 'element-symbol',
        alpha: 1.0
      })
      
      // Reset the component name
      new_component_name.value = ''
      
      // Refresh structure tree - 用户可以立即看到添加的内容
      refresh_structure_tree()
      
      // Clear selection status after creation
      await molstar_ref.value.viewerInstance.visual.select_none()
      has_selection.value = false
    } catch (e) {
      console.error('Failed to create component from selection:', e)
    }
  }

  const toggle_repr_visibility = async (reprRef) => {
    if (!molstar_ref.value?.viewerInstance) return
    try {
      await molstar_ref.value.viewerInstance.toggleRepresentationVisibility(reprRef)
      refresh_structure_tree()
    } catch (e) {
      console.error('Failed to toggle visibility:', e)
    }
  }

  const add_repr = async (componentRef, type) => {
    if (!molstar_ref.value?.viewerInstance) return
    try {
      // 🔹 使用新的 add_repr API
      let colorTheme = undefined
      let alpha = 1
      let params = {}
      
      // Add default params for different types
      if (type === 'ball-and-stick') {
        colorTheme = 'element-symbol'
        alpha = 1
      } else if (type === 'gaussian-surface') {
        colorTheme = 'hydrophobicity'
        alpha = 0.5
      } else if (type === 'label') {
        params = {
          typeParams: { level: granularity.value }
        }
      } else if (type === 'cartoon') {
        colorTheme = 'secondary-structure'
      }
      
      // Add representation to component using new API
      console.log('before add representation')
      await molstar_ref.value.viewerInstance.add_repr({
        componentRef,
        type,
        colorTheme,
        alpha,
        visible: true,
        params
      })
      console.log('after add representation')
      refresh_structure_tree()
    } catch (e) {
      console.error('Failed to add representation:', e)
    }
  }

  const change_repr_color = async (reprRef, colorTheme) => {
    if (!molstar_ref.value?.viewerInstance) return
    try {
      console.log('🎨 Changing color:', { reprRef, colorTheme })
      await molstar_ref.value.viewerInstance.changeRepresentationColor(reprRef, colorTheme)
      await nextTick()
      refresh_structure_tree()
    } catch (e) {
      console.error('❌ Failed to change representation color:', e)
    }
  }

  const change_repr_alpha = async (reprRef, alpha) => {
    if (!molstar_ref.value?.viewerInstance || isNaN(alpha)) {
      console.error('❌ Failed to change representation alpha: invalid params')
      return
    }
    try {
      const clampedAlpha = Math.max(0, Math.min(1, alpha))
      await molstar_ref.value.viewerInstance.changeRepresentationAlpha(reprRef, clampedAlpha)
      await nextTick()
      refresh_structure_tree()
    } catch (e) {
      console.error('❌ Failed to change representation alpha:', e)
    }
  }

  const delete_repr = async (reprRef) => {
    if (!molstar_ref.value?.viewerInstance) return
    try {
      await molstar_ref.value.viewerInstance.deleteRepresentation(reprRef)
      refresh_structure_tree()
    } catch (e) {
      console.error('Failed to delete representation:', e)
    }
  }

  // Contacts Group Management
  const are_all_contacts_visible = (contacts) => {
    if (!contacts || contacts.length === 0) return false
    return contacts.every(contact => contact.visible)
  }

  const toggle_all_contacts_visibility = async (structureRef, contacts) => {
    if (!molstar_ref.value?.viewerInstance || !contacts) return
    try {
      const allVisible = are_all_contacts_visible(contacts)
      console.log(`${allVisible ? '隐藏' : '显示'} ${structureRef} 的所有 ${contacts.length} 个 contacts`)
      
      for (const contact of contacts) {
        // 如果全部可见则隐藏，否则全部显示
        if (allVisible && contact.visible) {
          await molstar_ref.value.viewerInstance.toggleContactVisibility(contact.ref)
        } else if (!allVisible && !contact.visible) {
          await molstar_ref.value.viewerInstance.toggleContactVisibility(contact.ref)
        }
      }
      
      refresh_structure_tree()
    } catch (e) {
      console.error('Failed to toggle all contacts visibility:', e)
    }
  }

  const delete_all_contacts = async (structureRef, contacts) => {
    if (!molstar_ref.value?.viewerInstance || !contacts) return
    try {
      console.log(`🗑️ Deleting all ${contacts.length} contacts for ${structureRef}...`)
      
      for (const contact of contacts) {
        await molstar_ref.value.viewerInstance.remove_contact(contact.ref)
      }
      
      console.log(`✅ All ${contacts.length} contacts deleted for ${structureRef}`)
      refresh_structure_tree()
    } catch (e) {
      console.error('Failed to delete all contacts:', e)
    }
  }

  const set_ligand_view_id_visibility = (smiles_id) => {
    molstar_ref.value.viewerInstance.set_visibility('Ligand_' + smiles_id)
    molstar_ref.value.viewerInstance.set_visibility('Ligand_plus_' + smiles_id)

    for (let j = 0; j < pdb_ligand_inter_list.value.length; j++) {
      if (pdb_ligand_inter_list.value[j]['render_id'] == smiles_id) {
        for (let i = 0; i < pdb_ligand_inter_list.value[j].prolif_id_list.length; i++) {
          molstar_ref.value.viewerInstance.set_visibility(pdb_ligand_inter_list.value[j].prolif_id_list[i])
        }
        break
      }
    }
  }

  /**
   * 删除配体视图及其整个结构
   * @param smiles_id - 配体的唯一标识符
   */
  const remove_ligand_view_pdb = async (smiles_id) => {
    try {
      // 删除相互作用线
      await remove_prolif_line(smiles_id)
      
      // 删除整个配体结构（包含所有组件和表示）
      const deleted = await molstar_ref.value.viewerInstance.deleteStructure(smiles_id)
      
      if (deleted) {
        // 从列表中移除
        const index = pdb_ligand_inter_list.value.findIndex(item => item.render_id === smiles_id)
        if (index !== -1) {
          pdb_ligand_inter_list.value.splice(index, 1)
        }
        
        // 从2D相互作用配体列表中移除
        const ligand2dIndex = ligand_list_for_2d.value.findIndex(item => item.renderId === smiles_id)
        if (ligand2dIndex !== -1) {
          ligand_list_for_2d.value.splice(ligand2dIndex, 1)
          console.log(`✅ Removed ligand from 2D interaction list: ${smiles_id}`)
        }
        
        // 刷新结构树
        refresh_structure_tree()
        
        console.log(`✅ Deleted ligand structure: ${smiles_id}`)
      } else {
        console.warn(`⚠️ Ligand structure not found: ${smiles_id}`)
      }
    } catch (error) {
      console.error('Failed to remove ligand view:', error)
      throw error
    }
  }

  /**
   * 删除肽链视图及其整个结构
   * @param render_id - 肽链的唯一标识符
   */
  const remove_peptide_view_pdb = async (render_id) => {
    try {
      // 删除整个肽链结构（包含所有组件和表示）
      const deleted = await molstar_ref.value.viewerInstance.deleteStructure(render_id)
      
      if (deleted) {
        // 刷新结构树
        refresh_structure_tree()
        console.log(`✅ Deleted peptide structure: ${render_id}`)
      } else {
        console.warn(`⚠️ Peptide structure not found: ${render_id}`)
      }
    } catch (error) {
      console.error('Failed to remove peptide view:', error)
      throw error
    }
  }

  const set_background = (color) => {
    // {r, g, b}
    molstar_ref.value.viewerInstance.canvas.setBgColor(color)
  }

  const set_granularity = (value) => {
    molstar_ref.value.viewerInstance.visual.changeProps(value)
  }

  const quick_select = (item, type='single', not_focus) => {
    if (type === 'chains') {
      molstar_ref.value.viewerInstance.visual.select(pdb_info.value.chain)
    } else if (type === 'ligands') {
      molstar_ref.value.viewerInstance.visual.select(pdb_info.value.ligand)
    } else if (type === 'water') {
      molstar_ref.value.viewerInstance.visual.select([{'label_comp_id': 'HOH'}])
    } else {
      if (item?.length >= 1) {
        molstar_ref.value.viewerInstance.visual.select(item)
      } else {
        molstar_ref.value.viewerInstance.visual.select([item])
      }
    }
    if(!not_focus){
      molstar_ref.value.viewerInstance.visual.focus_now()
    }
  }

  const highlight_residues = (residues, focus=false) => {
    const plugin = molstar_ref.value.viewerInstance.plugin
    plugin.managers.interactivity.lociSelects.deselectAll()
    const structure = plugin.state.data.select('Structure_0')[0]?.obj?.data
    if (!structure || !residues?.length) return
    const key = (chain, number, insertion, name) =>
      JSON.stringify([chain, number, ['?', '.'].includes(insertion) ? '' : insertion || '', name])
    const selected = new Set(residues.map(item =>
      key(item.chain_id, item.residue_number, item.insertion_code, item.residue_name),
    ))
    const query = Queries.generators.atoms({
      residueTest: ({ element }) => selected.has(key(
        StructureProperties.chain.auth_asym_id(element).trim(),
        StructureProperties.residue.auth_seq_id(element),
        StructureProperties.residue.pdbx_PDB_ins_code(element),
        StructureProperties.atom.label_comp_id(element),
      )),
    })
    const loci = StructureSelection.toLociWithSourceUnits(StructureQuery.run(query, structure))
    plugin.managers.interactivity.lociSelects.select({ loci }, false)
    if (focus) plugin.managers.camera.focusLoci(loci)
  }


  /**
   * 查找并添加相互作用数据
   * @param item - 配体信息
   * @param structure_id - 实际的结构ID (如 '0', '1' 等)
   */
  const find_and_add_prolif_data = async (item, structure_id = '0') => {
    const bond_color_dict = {
      'VdWContact': ColorNames.orange,
      'PiStacking': ColorNames.purple,
      'Cationic': ColorNames.red,
      'HBDonor/HBAcceptor': ColorNames.blue,
      'HBDonor': ColorNames.blue,
      'HBAcceptor': ColorNames.blue
    }

    // 根据structure_id查找对应的render_id（从保存的数据中）
    // 注意：pdb_ligand_inter_list 中保存的是 render_id，但我们需要使用 structure_id 来创建 contact
    let prolif_data = []
    let prolif_id_list = []
    let pdb_string = ''
    let matched_render_id = structure_id // 默认使用 structure_id
    
    for(let i = 0; i < pdb_ligand_inter_list.value.length; i++) {
      // 尝试匹配 render_id（可能与 structure_id 相同或不同）
      if (pdb_ligand_inter_list.value[i].render_id == structure_id) {
        prolif_data = pdb_ligand_inter_list.value[i].prolif_data
        prolif_id_list = pdb_ligand_inter_list.value[i].prolif_id_list
        pdb_string = pdb_ligand_inter_list.value[i].pdb_string
        matched_render_id = pdb_ligand_inter_list.value[i].render_id
        break
      }
    }

    let tmp_list = []
    let interaction_list = []
    for (let i = 0; i < prolif_data.length; i++) {
      tmp_list = prolif_data[i].interaction_dict
      if (tmp_list.length > 0 && tmp_list[0]['ligand_chain_id'] == item['auth_asym_id'] && tmp_list[0]['ligand_residue_number'] == item['auth_residue_number']) {
        interaction_list = prolif_data[i].interaction_dict
        break
      }
    }

    // 过滤掉 Hydrophobic 相互作用
    const filtered_interaction_list = interaction_list.filter(item => item.interaction_type !== 'Hydrophobic')
    
    for (let i = 0; i < filtered_interaction_list.length; i++) {
      const prolif_id = 'Prolif_contact_' + structure_id + '_' + i
      prolif_id_list.push(prolif_id)

      await molstar_ref.value.viewerInstance.add_contact({
        structure_ref: 'Structure_' + structure_id,  // 使用实际的 structure_id
        start_query: [{'atom_id': filtered_interaction_list[i].ligand_atom_id}],
        end_query: [{'atom_id': filtered_interaction_list[i].prot_atom_id}],
        interactionType: filtered_interaction_list[i].interaction_type,
        color: bond_color_dict[filtered_interaction_list[i].interaction_type],
        id: prolif_id,
      })
    }
    
    // 刷新结构树以显示新创建的 contacts
    refresh_structure_tree()
  }

  const remove_prolif_line = async (render_id='0') => {
    for (let j = 0; j < pdb_ligand_inter_list.value.length; j++) {
      if (pdb_ligand_inter_list.value[j]['render_id'] == render_id) {
        const contactCount = pdb_ligand_inter_list.value[j].prolif_id_list.length
        for (let i = 0; i < pdb_ligand_inter_list.value[j].prolif_id_list.length; i++) {
          const contactId = pdb_ligand_inter_list.value[j].prolif_id_list[i]
          console.log(`  [${i + 1}/${contactCount}] Removing contact: ${contactId}`)
          await molstar_ref.value.viewerInstance.remove_contact(contactId)
        }
        pdb_ligand_inter_list.value[j].prolif_id_list = []
        
        console.log(`✅ All ${contactCount} contacts removed for render_id ${render_id}`)
        
        // 刷新结构树
        refresh_structure_tree()
        break
      }
    }
  }

  const expand_selection = () => {
    molstar_ref.value.viewerInstance.visual.expand_select(Number(expand_number.value))
  }

  const select_all = () => {
    molstar_ref.value.viewerInstance.visual.select_all()
  }

  const select_none = () => {
    molstar_ref.value.viewerInstance.visual.select_none()
  }

  const invert_select = () => {
    molstar_ref.value.viewerInstance.visual.inverse_select()
  }

  const change_water_repr = () => {
    molstar_ref.value.viewerInstance.set_visibility('Water')
  }

  const show_interaction_dialog = () => {
    show_prolif.value = !show_prolif.value
    if (show_prolif.value) emit('request-2d')
  }
  watch(() => props.interaction_2d, value => {
    if (!value) show_prolif.value = false
    if (show_prolif.value && value?.status === 'not_requested') emit('request-2d')
  }, { flush: 'post' })
  const select_2d_residue = async (key) => {
    show_prolif.value = false
    await nextTick()
    emit('residue-select', key)
  }

  /**
   * 显示指定配体或肽链的相互作用
   * @param render_id - 配体或肽链的ID（或组件引用）
   * @param structure_id - 结构ID（可选，默认与 render_id 相同）
   * @param component_ref - 组件引用（可选，如果不提供则自动判断）
   */
  const show_interactions = async (render_id, structure_id, component_ref) => {
    try {
      const actualStructureId = structure_id || render_id
      
      // 使用 molstar 内置的相互作用计算功能
      let reprRef
      
      if (component_ref) {
        // 如果明确指定了组件引用，使用通用方法
        reprRef = await molstar_ref.value.viewerInstance.show_component_interactions(
          component_ref,
          actualStructureId
        )
      } else {
        // 否则假设是配体，使用配体方法
        reprRef = await molstar_ref.value.viewerInstance.show_ligand_interactions(
          render_id,
          actualStructureId
        )
      }
      
      // 保存 reprRef 用于后续隐藏/删除
      // 可以存储在 pdb_ligand_inter_list 中或单独的数组中
      console.log(`✅ Showed interactions for ${component_ref || render_id}, reprRef: ${reprRef}`)
      
      // 刷新结构树以显示新的表示
      refresh_structure_tree()
      
      return reprRef
    } catch (error) {
      console.error('Failed to show interactions:', error)
      throw error
    }
  }

  /**
   * 隐藏指定配体或肽链的相互作用
   * @param reprRef - 表示引用（由 show_interactions 返回）
   */
  const hide_interactions = async (reprRef) => {
    try {
      await molstar_ref.value.viewerInstance.deleteRepresentation(reprRef)
      console.log(`✅ Hid interactions: ${reprRef}`)
      
      // 刷新结构树
      refresh_structure_tree()
    } catch (error) {
      console.error('Failed to hide interactions:', error)
      throw error
    }
  }

  const showChain = async (chainId) => {
    await molstar_ref.value.viewerInstance.visual.showChain(chainId)
  }

  const hideChain = async (chainId) => {
    console.log(`✅ Hiding chain: ${chainId}`)
    await molstar_ref.value.viewerInstance.visual.hideChain(chainId)
  }

  const showLigand = async (chainId, resId, resName) => {
    await molstar_ref.value.viewerInstance.visual.showLigand(chainId, resId, resName)
  }

  const hideLigand = async (chainId, resId, resName) => {
    await molstar_ref.value.viewerInstance.visual.hideLigand(chainId, resId, resName)
  }

  onMounted(async () => {
    // Tells listeners whether the 3D view can be used, so a failed start is not reported as a problem with the file.
    let ready = true
    try {
      initialization = init()
      await initialization

    } catch (error) {
      ready = false
      console.error('Molstar initialization failed:', error)
      webgl_error_dialog.value = true
    } finally {
      if (!disposed) emit('init-complete', ready)
    }
  })

  // Watch for structure tree popover opening and check selection
  watch(structure_tree_open, (isOpen) => {
    if (isOpen) {
      check_selection()
    }
  })

  defineExpose({
    init,
    reset_all,
    load_structure,
    clear_structure,
    load_overlay,
    get_overlay_id,
    set_overlay_visible,
    set_background,
    toggle_spin,
    full_screen,
    full_screen_type,
    add_shape,
    remove_shape,
    reset_camera,
    add_mouse_event,
    expand_selection,
    granularity,
    expand_number,
    pdb_info,
    show_tool,
    quick_select,
    highlight_residues,
    get_pdb_info,
    set_ligand_view_id_visibility,
    remove_ligand_view_pdb,
    select_none,
    change_water_repr,
    show_interaction_dialog,
    set_visibility,
    set_peptide_view_id_visibility,
    remove_peptide_view_pdb,
    refresh_structure_tree,
    structure_tree,
    show_interactions,
    hide_interactions,
    showChain,
    hideChain,
    showLigand,
    hideLigand
  })

</script>

<style>
  .drugflow_molstar .msp-layout-main {
    top: 0px!important;
    bottom: 97px!important;
  }
  .drugflow_molstar_no_sequence .msp-layout-main {
    bottom: 0px!important;
  }
  .drugflow_molstar .msp-layout-top {
    bottom: 0!important;
    top: auto!important;
  }
  .drugflow_molstar .msp-plugin .msp-viewport-top-left-controls {
    display: none;
  }
  .drugflow_molstar .msp-plugin .msp-selection-viewport-controls {
    display: none;
  }
  .drugflow_molstar .msp-plugin .msp-viewport-controls {
    display: none;
  }
  .drugflow_molstar .msp-plugin .msp-layout-standard {
    border: none;
  }
</style>
