import { api } from "@/lib/api-client";

export interface UserItem {
  id: string;
  tenant_id: string;
  email: string;
  role: string;
  has_password: boolean;
  created_at: string;
}

export interface UserCreate {
  email: string;
  role?: string;
  password: string;
  tenant_id?: string;
}

export interface UserPatch {
  email?: string;
  role?: string;
  password?: string;
}

export const usersApi = {
  list: async () => (await api.get<UserItem[]>("/users")).data,
  create: async (body: UserCreate) => (await api.post<UserItem>("/users", body)).data,
  patch: async (id: string, body: UserPatch) =>
    (await api.patch<UserItem>(`/users/${id}`, body)).data,
  remove: async (id: string) => {
    await api.delete(`/users/${id}`);
  },
};
