/** Attach a job photo or document (PDF, Word, image, text): the server reads the text (₹0, on the server) and the
 * app puts it in the message box. Files travel as base64 JSON, the same path on web and phones
 * (Expo's native fetch can't send React Native's {uri} FormData parts). */
import * as DocumentPicker from 'expo-document-picker';
import { File } from 'expo-file-system';
import * as ImagePicker from 'expo-image-picker';
import { Platform } from 'react-native';

import { api } from './api';

const MAX_MB = 10;
const DOC_TYPES = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document', // .docx
  'text/plain',
  'image/*',
];

export type Attached = { name: string; text: string; truncated: boolean };

function webBase64(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] ?? ''); // drop "data:...;base64,"
    reader.onerror = () => reject(new Error("Couldn't open that file."));
    reader.readAsDataURL(file);
  });
}

async function read(name: string, base64: string): Promise<Attached> {
  const { data } = await api.post<{ text: string; truncated: boolean }>(
    '/chat/extract',
    { filename: name, data: base64 },
    { timeout: 120_000 }, // scanned PDFs are OCR'd page by page
  );
  return { name, ...data };
}

/** null = the user closed the picker. */
export async function attachPhoto(): Promise<Attached | null> {
  const picked = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.8, base64: true });
  if (picked.canceled) return null;
  const a = picked.assets[0];
  if (!a.base64) throw new Error("Couldn't open that photo.");
  const ext = a.mimeType === 'image/png' ? 'png' : a.mimeType === 'image/webp' ? 'webp' : 'jpg';
  return read(a.fileName ?? `photo.${ext}`, a.base64);
}

/** Pick a file and read it as base64 (web: FileReader; phones: expo-file-system). null = picker closed. */
export async function pickFile(types: string[], maxMb: number): Promise<{ name: string; base64: string } | null> {
  const picked = await DocumentPicker.getDocumentAsync({ type: types, copyToCacheDirectory: true });
  if (picked.canceled) return null;
  const a = picked.assets[0];
  if (a.size && a.size > maxMb * 1024 * 1024) throw new Error(`That file is bigger than ${maxMb} MB.`);
  const base64 = Platform.OS === 'web' && a.file ? await webBase64(a.file) : await new File(a.uri).base64();
  return { name: a.name, base64 };
}

export async function attachDocument(): Promise<Attached | null> {
  const f = await pickFile(DOC_TYPES, MAX_MB);
  return f ? read(f.name, f.base64) : null;
}

/** What goes into the message box. */
export function attachedMessage({ name, text, truncated }: Attached): string {
  const cut = truncated ? '\n\n(Only the first part of a long file is used.)' : '';
  return `Check this job for me (from ${name}):\n\n${text.trim()}${cut}`;
}
