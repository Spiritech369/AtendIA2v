import { formatDistanceToNow } from "date-fns";
import { es } from "date-fns/locale";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Save,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import type { CustomerNote, FieldDefinition } from "@/features/customers/api";
import {
  useCreateNote,
  useCustomerDetail,
  useCustomerNotes,
  useDeleteNote,
  useFieldDefinitions,
  useFieldValues,
  usePatchCustomer,
  usePutFieldValues,
  useUpdateNote,
} from "@/features/conversations/hooks/useContactPanel";

interface Props {
  customerId: string | undefined;
}

export function ContactPanel({ customerId }: Props) {
  const [collapsed, setCollapsed] = useState(false);

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => setCollapsed(false)}
        className="flex h-full w-3 shrink-0 cursor-pointer items-center justify-center rounded-md border bg-muted/40 transition-colors hover:bg-muted"
      >
        <ChevronLeft className="h-3 w-3 text-muted-foreground" />
      </button>
    );
  }

  return (
    <Card className="flex w-80 shrink-0 flex-col overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between py-2 px-3">
        <CardTitle className="text-sm">Contacto</CardTitle>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => setCollapsed(true)}>
          <ChevronRight className="h-3 w-3" />
        </Button>
      </CardHeader>
      <Separator />
      <ScrollArea className="flex-1">
        <div className="space-y-0">
          {customerId ? (
            <>
              <BasicInfoSection customerId={customerId} />
              <Separator />
              <CustomFieldsSection customerId={customerId} />
              <Separator />
              <NotesSection customerId={customerId} />
            </>
          ) : (
            <div className="p-4 text-sm text-muted-foreground">
              Selecciona una conversación.
            </div>
          )}
        </div>
      </ScrollArea>
    </Card>
  );
}

// ── Basic Info ───────────────────────────────────────────────────────

function BasicInfoSection({ customerId }: { customerId: string }) {
  const customer = useCustomerDetail(customerId);
  const patch = usePatchCustomer(customerId);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");

  useEffect(() => {
    if (customer.data) setName(customer.data.name ?? "");
  }, [customer.data]);

  if (customer.isLoading) return <Skeleton className="m-4 h-20" />;
  if (!customer.data) return null;

  const c = customer.data;

  const save = () => {
    patch.mutate({ name: name.trim() || undefined }, { onSuccess: () => setEditing(false) });
  };

  return (
    <div className="space-y-3 p-4">
      <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
        Info básica
      </div>
      {editing ? (
        <div className="space-y-2">
          <div>
            <Label className="text-xs">Nombre</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="h-8 text-sm"
              onKeyDown={(e) => {
                if (e.key === "Enter") save();
                if (e.key === "Escape") setEditing(false);
              }}
            />
          </div>
          <div className="flex gap-1">
            <Button size="sm" className="h-7 text-xs" onClick={save} disabled={patch.isPending}>
              <Save className="mr-1 h-3 w-3" /> Guardar
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs"
              onClick={() => {
                setName(c.name ?? "");
                setEditing(false);
              }}
            >
              Cancelar
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">{c.name || "(sin nombre)"}</span>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => setEditing(true)}
            >
              <Pencil className="h-3 w-3" />
            </Button>
          </div>
          <div className="text-xs text-muted-foreground">{c.phone_e164}</div>
        </div>
      )}
    </div>
  );
}

// ── Custom Fields ────────────────────────────────────────────────────

function CustomFieldsSection({ customerId }: { customerId: string }) {
  const defs = useFieldDefinitions();
  const vals = useFieldValues(customerId);
  const putValues = usePutFieldValues(customerId);
  const [draft, setDraft] = useState<Record<string, string | null>>({});
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (vals.data) {
      const map: Record<string, string | null> = {};
      for (const v of vals.data) map[v.key] = v.value;
      setDraft(map);
      setDirty(false);
    }
  }, [vals.data]);

  if (defs.isLoading || vals.isLoading) return <Skeleton className="m-4 h-16" />;
  if (!defs.data?.length) {
    return (
      <div className="p-4">
        <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
          Campos personalizados
        </div>
        <div className="text-xs text-muted-foreground">Sin campos definidos.</div>
      </div>
    );
  }

  const update = (key: string, value: string | null) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
    setDirty(true);
  };

  const save = () => {
    putValues.mutate(draft, { onSuccess: () => setDirty(false) });
  };

  return (
    <div className="space-y-3 p-4">
      <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
        Campos personalizados
      </div>
      <div className="space-y-2">
        {defs.data.map((d) => (
          <FieldInput key={d.id} definition={d} value={draft[d.key] ?? ""} onChange={update} />
        ))}
      </div>
      {dirty && (
        <Button
          size="sm"
          className="h-7 text-xs"
          onClick={save}
          disabled={putValues.isPending}
        >
          <Save className="mr-1 h-3 w-3" />
          {putValues.isPending ? "Guardando..." : "Guardar campos"}
        </Button>
      )}
    </div>
  );
}

function FieldInput({
  definition,
  value,
  onChange,
}: {
  definition: FieldDefinition;
  value: string;
  onChange: (key: string, value: string | null) => void;
}) {
  const { key, label, field_type, field_options } = definition;

  if (field_type === "select") {
    const choices = (field_options as { choices?: string[] } | null)?.choices ?? [];
    return (
      <div>
        <Label className="text-xs">{label}</Label>
        <Select value={value || ""} onValueChange={(v) => onChange(key, v)}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder="Seleccionar..." />
          </SelectTrigger>
          <SelectContent>
            {choices.map((c) => (
              <SelectItem key={c} value={c}>
                {c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    );
  }

  if (field_type === "checkbox") {
    const checked = value === "true";
    return (
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onChange(key, checked ? "false" : "true")}
          className={`flex h-5 w-5 shrink-0 items-center justify-center rounded border text-xs ${checked ? "border-primary bg-primary text-primary-foreground" : "border-input"}`}
        >
          {checked && <Check className="h-3 w-3" />}
        </button>
        <Label className="text-xs">{label}</Label>
      </div>
    );
  }

  const inputType = field_type === "number" ? "number" : field_type === "date" ? "date" : "text";

  return (
    <div>
      <Label className="text-xs">{label}</Label>
      <Input
        type={inputType}
        value={value}
        onChange={(e) => onChange(key, e.target.value)}
        className="h-8 text-xs"
      />
    </div>
  );
}

// ── Notes ────────────────────────────────────────────────────────────

function NotesSection({ customerId }: { customerId: string }) {
  const notes = useCustomerNotes(customerId);
  const createNote = useCreateNote(customerId);
  const [composing, setComposing] = useState(false);
  const [newContent, setNewContent] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (composing) textareaRef.current?.focus();
  }, [composing]);

  const submit = () => {
    const text = newContent.trim();
    if (!text) return;
    createNote.mutate(
      { content: text },
      {
        onSuccess: () => {
          setNewContent("");
          setComposing(false);
        },
      },
    );
  };

  return (
    <div className="space-y-3 p-4">
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Notas
        </div>
        {!composing && (
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={() => setComposing(true)}
          >
            <Plus className="h-3 w-3" />
          </Button>
        )}
      </div>

      {composing && (
        <div className="space-y-1.5 rounded-md border p-2">
          <Textarea
            ref={textareaRef}
            value={newContent}
            onChange={(e) => setNewContent(e.target.value)}
            placeholder="Escribe una nota..."
            rows={3}
            className="text-xs"
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                submit();
              }
              if (e.key === "Escape") {
                setComposing(false);
                setNewContent("");
              }
            }}
          />
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-muted-foreground">Ctrl+Enter para guardar</span>
            <div className="flex gap-1">
              <Button
                size="sm"
                className="h-6 text-xs px-2"
                onClick={submit}
                disabled={!newContent.trim() || createNote.isPending}
              >
                Guardar
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-6 text-xs px-2"
                onClick={() => {
                  setComposing(false);
                  setNewContent("");
                }}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          </div>
        </div>
      )}

      {notes.isLoading && <Skeleton className="h-16" />}
      {notes.data?.length === 0 && !composing && (
        <div className="text-xs text-muted-foreground">Sin notas.</div>
      )}
      {notes.data?.map((note) => (
        <NoteCard key={note.id} note={note} customerId={customerId} />
      ))}
    </div>
  );
}

function NoteCard({ note, customerId }: { note: CustomerNote; customerId: string }) {
  const updateNote = useUpdateNote(customerId);
  const deleteNote = useDeleteNote(customerId);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState(note.content);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const wasEdited = note.updated_at !== note.created_at;
  const relativeTime = formatDistanceToNow(new Date(note.created_at), {
    addSuffix: true,
    locale: es,
  });

  const saveEdit = () => {
    const text = editContent.trim();
    if (!text) return;
    updateNote.mutate(
      { noteId: note.id, content: text },
      { onSuccess: () => setEditing(false) },
    );
  };

  const togglePin = () => {
    updateNote.mutate({ noteId: note.id, pinned: !note.pinned });
  };

  const doDelete = () => {
    deleteNote.mutate(note.id, { onSuccess: () => setConfirmDelete(false) });
  };

  return (
    <div
      className={`rounded-md border p-2 text-xs space-y-1.5 ${note.pinned ? "border-amber-400 bg-amber-50 dark:bg-amber-950/20" : ""}`}
    >
      <div className="flex items-start justify-between gap-1">
        <div className="flex-1 min-w-0">
          <span className="font-medium">{note.author_email ?? "Sistema"}</span>
          <span className="text-muted-foreground"> · {relativeTime}</span>
          {wasEdited && <span className="text-muted-foreground"> · editada</span>}
          {note.pinned && (
            <Badge variant="outline" className="ml-1 h-4 px-1 text-[10px]">
              <Pin className="mr-0.5 h-2 w-2" /> Fijada
            </Badge>
          )}
        </div>
        <div className="flex shrink-0 gap-0.5">
          <Button variant="ghost" size="icon" className="h-5 w-5" onClick={togglePin}>
            {note.pinned ? <PinOff className="h-3 w-3" /> : <Pin className="h-3 w-3" />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5"
            onClick={() => {
              setEditContent(note.content);
              setEditing(true);
            }}
          >
            <Pencil className="h-3 w-3" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5 text-destructive hover:text-destructive"
            onClick={() => setConfirmDelete(true)}
          >
            <Trash2 className="h-3 w-3" />
          </Button>
        </div>
      </div>

      {editing ? (
        <div className="space-y-1">
          <Textarea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            rows={3}
            className="text-xs"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                saveEdit();
              }
              if (e.key === "Escape") setEditing(false);
            }}
          />
          <div className="flex gap-1">
            <Button
              size="sm"
              className="h-6 text-xs px-2"
              onClick={saveEdit}
              disabled={updateNote.isPending}
            >
              Guardar
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-6 text-xs px-2"
              onClick={() => setEditing(false)}
            >
              Cancelar
            </Button>
          </div>
        </div>
      ) : (
        <p className="whitespace-pre-wrap">{note.content}</p>
      )}

      {confirmDelete && (
        <div className="flex items-center gap-2 rounded bg-destructive/10 p-1.5">
          <span className="flex-1">Eliminar esta nota?</span>
          <Button
            size="sm"
            variant="destructive"
            className="h-6 text-xs px-2"
            onClick={doDelete}
            disabled={deleteNote.isPending}
          >
            Eliminar
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-6 text-xs px-2"
            onClick={() => setConfirmDelete(false)}
          >
            No
          </Button>
        </div>
      )}
    </div>
  );
}
