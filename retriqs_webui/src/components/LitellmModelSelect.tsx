import React, { useState } from 'react';
import { AsyncSelect } from '@/components/ui/AsyncSelect';

interface LiteLLMModelOption {
    value: string;
    label: string;
    provider: string;
    mode: string;
    metadata: any;
}

const MANUAL_OLLAMA_OPTIONS: LiteLLMModelOption[] = [
    {
        value: 'qwen3:0.6B',
        label: 'qwen3:0.6B',
        provider: 'ollama',
        mode: 'chat',
        metadata: {}
    },
    {
        value: 'bge-m3:latest',
        label: 'bge-m3:latest',
        provider: 'ollama',
        mode: 'embedding',
        metadata: {
            output_vector_size: 1024
        }
    }
];

const ensureManualOllamaOptions = (
    options: LiteLLMModelOption[],
    modeFilter?: 'chat' | 'embedding',
    allowedProviders?: string[]
): LiteLLMModelOption[] => {
    const shouldIncludeOllamaManualOptions =
        !allowedProviders || allowedProviders.includes('ollama');

    if (!shouldIncludeOllamaManualOptions) {
        return options;
    }

    const ensured = [...options];
    for (const manualOption of MANUAL_OLLAMA_OPTIONS) {
        if (modeFilter && manualOption.mode !== modeFilter) continue;
        const exists = ensured.some((opt) => opt.value === manualOption.value);
        if (!exists) {
            ensured.push(manualOption);
        }
    }

    return ensured;
};

const normalizeModelValue = (modelKey: string, providerHint?: string): string => {
    if (!modelKey) return modelKey;
    if (modelKey.startsWith('ollama/')) {
        return modelKey.slice('ollama/'.length);
    }
    return modelKey;
};

const formatModelLabel = (modelKey: string): string => {
    return normalizeModelValue(modelKey);
};

const fetchLitellmModels = async (modeFilter?: 'chat' | 'embedding', allowedProviders?: string[]): Promise<LiteLLMModelOption[]> => {
    try {
        const cacheKey = `litellm_models_v3_${modeFilter || 'all'}_${allowedProviders ? allowedProviders.join('_') : 'all'}`;
        const cached = sessionStorage.getItem(cacheKey);
        if (cached) {
            const cachedOptions = JSON.parse(cached) as LiteLLMModelOption[];
            const ensuredCachedOptions = ensureManualOllamaOptions(cachedOptions, modeFilter, allowedProviders);
            ensuredCachedOptions.sort((a, b) => a.label.localeCompare(b.label));
            return ensuredCachedOptions;
        }

        // also need a general cache to not double-fetch
        let rawData = sessionStorage.getItem('litellm_raw_data');
        if (!rawData) {
            const res = await fetch('https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json');
            rawData = await res.text();
            sessionStorage.setItem('litellm_raw_data', rawData);
        }

        const data = JSON.parse(rawData);
        const options: LiteLLMModelOption[] = [];

        for (const [key, value] of Object.entries(data)) {
            if (key === 'sample_spec') continue;

            const modelData = value as any;
            if (modeFilter === 'chat') {
                if (modelData.mode !== 'chat' && modelData.mode !== 'completion') continue;
            } else if (modeFilter && modelData.mode !== modeFilter) {
                continue;
            }
            if (allowedProviders && !allowedProviders.includes(modelData.litellm_provider)) continue;

            const normalizedValue = normalizeModelValue(key, modelData.litellm_provider);
            options.push({
                value: normalizedValue,
                label: formatModelLabel(normalizedValue),
                provider: modelData.litellm_provider,
                mode: modelData.mode,
                metadata: modelData
            });
        }

        const finalOptions = ensureManualOllamaOptions(options, modeFilter, allowedProviders);

        // Sort alphabetically
        finalOptions.sort((a, b) => a.label.localeCompare(b.label));

        sessionStorage.setItem(cacheKey, JSON.stringify(finalOptions));
        return finalOptions;
    } catch (e) {
        console.error("Failed to fetch litellm models", e);
        return [];
    }
};

interface LitellmModelSelectProps {
    mode: 'chat' | 'embedding';
    value: string;
    onChange: (value: string, option?: LiteLLMModelOption) => void;
    disabled?: boolean;
    allowedProviders?: string[];
}

export const LitellmModelSelect: React.FC<LitellmModelSelectProps> = ({ mode, value, onChange, disabled, allowedProviders }) => {
    const [optionsCache, setOptionsCache] = useState<LiteLLMModelOption[]>([]);
    const providerHint = allowedProviders?.length === 1 ? allowedProviders[0] : undefined;
    const normalizedCurrentValue = normalizeModelValue(value, providerHint);

    const fetcherWrapper = async () => {
        const opts = await fetchLitellmModels(mode, allowedProviders);
        setOptionsCache(opts);
        return opts;
    };

    return (
        <AsyncSelect<LiteLLMModelOption>
            fetcher={fetcherWrapper}
            preload={true}
            value={normalizedCurrentValue}
            onChange={(val) => {
                const normalizedValue = normalizeModelValue(val, providerHint);
                const selectedOpt = optionsCache.find(o => o.value === normalizedValue);
                if (selectedOpt) {
                    onChange(normalizedValue, selectedOpt);
                } else {
                    // It's a custom manually typed model
                    onChange(normalizedValue, {
                        value: normalizedValue,
                        label: formatModelLabel(normalizedValue),
                        provider: 'custom',
                        mode: mode,
                        metadata: {}
                    });
                }
            }}
            filterFn={(option, query) =>
                option.label.toLowerCase().includes(query.toLowerCase()) ||
                Boolean(option.provider?.toLowerCase().includes(query.toLowerCase()))
            }
            renderOption={(option) => (
                <div className="flex flex-col gap-1 w-[90%] text-left">
                    <span className="font-medium text-sm truncate">{option.label}</span>
                    <div className="flex gap-2 text-[10px] text-muted-foreground">
                        <span className="bg-muted px-1.5 py-0.5 rounded capitalize truncate max-w-[100px]">{option.provider || 'custom'}</span>
                        {option.metadata?.max_input_tokens && (
                            <span>{option.metadata.max_input_tokens.toLocaleString()} tokens ctx</span>
                        )}
                    </div>
                </div>
            )}
            getOptionValue={(opt) => typeof opt === 'string' ? opt : (opt?.value || '')}
            getDisplayValue={(opt) => typeof opt === 'string' ? opt : (opt?.label || '')}
            placeholder={`Select ${mode === 'chat' ? 'LLM' : 'Embedding'} model...`}
            searchPlaceholder="Search by model or provider..."
            className="w-full"
            triggerClassName="w-full bg-background mt-1"
            disabled={disabled}
            creatable={true}
            customOptionLabel={(query) => (
                <div className="flex flex-col gap-1 w-[90%] text-left">
                    <span className="font-medium text-sm truncate italic">Use custom model: "{query}"</span>
                </div>
            )}
        />
    );
};
