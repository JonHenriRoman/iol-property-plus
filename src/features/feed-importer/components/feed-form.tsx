'use client';

import { useActionState, useState } from 'react';

import Button from '@/components/ui/button';
import Field, { inputClass, TextInput } from '@/components/ui/field';
import { getVendor, VENDORS } from '@/lib/feed-vendors';

import type { FormState } from '../server/actions';

type Initial = {
  code: string;
  name: string;
  vendorSlug: string;
  baseUrl: string | null;
  authConfig: Record<string, unknown>;
};

type Action = (prev: FormState, formData: FormData) => Promise<FormState>;

const EMPTY: FormState = { ok: false };

const valueFor = (
  initial: Initial | undefined,
  key: string,
  target: 'base_url' | 'auth_config',
) => {
  if (!initial) return '';
  if (target === 'base_url') return initial.baseUrl ?? '';
  const raw = initial.authConfig[key];
  if (Array.isArray(raw)) return raw.join(', ');
  return raw == null ? '' : String(raw);
};

const inputTypeFor = (field: { sensitive?: boolean; type: 'text' | 'url' }): string => {
  if (field.sensitive) return 'password';
  return field.type === 'url' ? 'url' : 'text';
};

const FeedForm = ({
  mode,
  action,
  initial,
}: {
  mode: 'create' | 'edit';
  action: Action;
  initial?: Initial;
}) => {
  const [state, formAction, pending] = useActionState(action, EMPTY);
  const firstSlug = initial?.vendorSlug || VENDORS[0]!.slug;
  const [vendorSlug, setVendorSlug] = useState(firstSlug);
  const [code, setCode] = useState(initial?.code ?? `${firstSlug}-`);
  const vendor = getVendor(vendorSlug)!;
  const errors = state.fieldErrors ?? {};

  const onVendorChange = (slug: string) => {
    setVendorSlug(slug);
    if (mode === 'create') setCode(`${slug}-`);
  };

  return (
    <form action={formAction} className="flex max-w-xl flex-col gap-5">
      <Field help={`Feed format: ${vendor.feedFormat}.`} id="vendor" label="Vendor">
        <select
          className={inputClass}
          disabled={mode === 'edit'}
          name="vendor"
          onChange={(e) => onVendorChange(e.target.value)}
          value={vendorSlug}
        >
          {VENDORS.map((v) => (
            <option key={v.slug} value={v.slug}>
              {v.label}
            </option>
          ))}
        </select>
      </Field>
      {mode === 'edit' ? <input name="vendor" type="hidden" value={vendorSlug} /> : null}

      <Field
        error={errors.code}
        help={`A unique identifier. Convention: start with "${vendor.slug}-".`}
        id="code"
        label="Feed code"
      >
        <TextInput
          name="code"
          onChange={(e) => setCode(e.target.value)}
          readOnly={mode === 'edit'}
          required
          spellCheck={false}
          value={code}
        />
      </Field>

      <Field error={errors.name} id="name" label="Feed name">
        <TextInput
          defaultValue={initial?.name ?? ''}
          name="name"
          placeholder="e.g. Acme Realty — Sea Point"
          required
        />
      </Field>

      {vendor.fields.map((f) => (
        <Field error={errors[f.key]} help={f.help} id={f.key} key={f.key} label={f.label}>
          <TextInput
            autoComplete={f.sensitive ? 'off' : undefined}
            defaultValue={valueFor(initial, f.key, f.target)}
            name={f.key}
            placeholder={f.type === 'url' ? 'https://…' : undefined}
            required={f.required}
            spellCheck={false}
            type={inputTypeFor(f)}
          />
        </Field>
      ))}

      <p className="rounded-md border border-line bg-surface px-3 py-2 text-xs text-ink-muted">
        <span className="font-medium text-ink">Credentials:</span> {vendor.secretsNote} They are not
        entered here.
      </p>

      <input name="isActive" type="hidden" value="true" />

      <div className="flex items-center gap-3">
        <Button disabled={pending} type="submit" variant="primary">
          {pending ? 'Saving…' : mode === 'create' ? 'Create feed' : 'Save changes'}
        </Button>
        {state.message ? (
          <span className={`text-sm ${state.ok ? 'text-ok' : 'text-danger'}`} role="status">
            {state.message}
          </span>
        ) : null}
      </div>
    </form>
  );
};

export default FeedForm;
