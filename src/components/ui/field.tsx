import { cloneElement, type InputHTMLAttributes, isValidElement, type ReactElement } from 'react';

/**
 * Label + control + help/error, wired for accessibility: the label is bound with
 * `htmlFor`, and help/error text is linked onto the control via
 * `aria-describedby` (+ `aria-invalid` when there is an error). The single child
 * is the control — an `<input>`, `<select>`, `<textarea>` or a wrapper that
 * forwards these props.
 */
const Field = ({
  id,
  label,
  help,
  error,
  children,
}: {
  id: string;
  label: string;
  help?: string;
  error?: string;
  children: ReactElement<{ id?: string; 'aria-describedby'?: string; 'aria-invalid'?: boolean }>;
}) => {
  const helpId = help ? `${id}-help` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [helpId, errorId].filter(Boolean).join(' ') || undefined;

  const control = isValidElement(children)
    ? cloneElement(children, {
        id,
        'aria-describedby': describedBy,
        'aria-invalid': error ? true : undefined,
      })
    : children;

  return (
    <div className="flex flex-col gap-1">
      <label className="text-sm font-medium text-ink" htmlFor={id}>
        {label}
      </label>
      {control}
      {help ? (
        <p className="text-xs text-ink-muted" id={helpId}>
          {help}
        </p>
      ) : null}
      {error ? (
        <p className="text-xs text-danger" id={errorId}>
          {error}
        </p>
      ) : null}
    </div>
  );
};

const inputClass =
  'rounded-md border border-line bg-raised px-2.5 py-1.5 text-sm text-ink outline-none aria-[invalid=true]:border-danger focus-visible:border-accent focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent';

const TextInput = ({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) => {
  return <input className={`${inputClass} ${className ?? ''}`} {...props} />;
};

export default Field;
export { inputClass, TextInput };
