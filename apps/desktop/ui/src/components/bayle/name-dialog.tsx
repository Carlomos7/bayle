import { useId, type ReactNode } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { Input } from './controls';
import { Dialog } from './overlay';

export interface NameDialogProps {
  open?: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  label?: string;
  initial?: string;
  placeholder?: string;
  submitLabel: string;
  /** Names already in use (compared without case). The initial name is always allowed. */
  taken?: readonly string[];
  takenMessage?: string;
  /** Allow an empty name (the caller supplies a fallback). */
  optional?: boolean;
  /** Rename mode: submitting the initial name unchanged just closes. */
  rename?: boolean;
  /** Called with the trimmed name. */
  onSubmit: (name: string) => void;
}

/**
 * One text field, validated with Zod: required, at most 80 characters, and
 * not one of `taken`. Used for new profile, renames and "keep a copy".
 */
export function NameDialog({ open = true, onOpenChange, title, description, label = 'Name', initial = '', placeholder, submitLabel, taken = [], takenMessage = 'That name is already used.', optional, rename, onSubmit }: NameDialogProps) {
  const formId = useId();
  const used = new Set(taken.map((t) => t.toLowerCase()).filter((t) => t !== initial.trim().toLowerCase()));
  const schema = z.object({
    name: z.string().trim()
      .max(80, 'Keep it under 80 characters.')
      .refine((v) => optional || v.length > 0, 'Give it a name.')
      .refine((v) => !used.has(v.toLowerCase()), takenMessage),
  });
  const form = useForm<z.input<typeof schema>, unknown, z.output<typeof schema>>({ resolver: zodResolver(schema), defaultValues: { name: initial }, mode: 'onChange' });
  const submit = form.handleSubmit(({ name }) => {
    onOpenChange(false);
    if (!rename || name !== initial.trim()) onSubmit(name);
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={title} description={description}
      footer={<><Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button><Button variant="primary" type="submit" form={formId} disabled={!form.formState.isValid}>{submitLabel}</Button></>}>
      <Form {...form}>
        <form id={formId} onSubmit={(e) => void submit(e)} noValidate>
          <FormField control={form.control} name="name" render={({ field }) => (
            <FormItem>
              <FormLabel>{label}</FormLabel>
              {/* A dialog that asks for one value focuses it, as the WAI-ARIA dialog pattern recommends. */}
              {/* eslint-disable-next-line jsx-a11y/no-autofocus */}
              <FormControl><Input autoFocus placeholder={placeholder} {...field} /></FormControl>
              <FormMessage />
            </FormItem>
          )} />
        </form>
      </Form>
    </Dialog>
  );
}
