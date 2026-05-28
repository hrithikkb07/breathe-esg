import axios from "axios";

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000/api";

export const api = axios.create({
  baseURL: BASE_URL,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true;
      try {
        const refresh = localStorage.getItem("refresh_token");
        const { data } = await axios.post(`${BASE_URL}/auth/token/refresh/`, { refresh });
        localStorage.setItem("access_token", data.access);
        original.headers.Authorization = `Bearer ${data.access}`;
        return api(original);
      } catch {
        localStorage.clear();
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export const authApi = {
  login: (username, password) => api.post("/auth/token/", { username, password }),
};

export const dashboardApi = {
  summary: () => api.get("/dashboard/summary/"),
};

export const uploadsApi = {
  list: (params) => api.get("/uploads/", { params }),
  upload: (formData) =>
    api.post("/uploads/", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    }),
  failedRows: (uploadId) => api.get(`/uploads/${uploadId}/failed-rows/`),
};

export const recordsApi = {
  list: (params) => api.get("/records/", { params }),
  detail: (id)   => api.get(`/records/${id}/`),
  review: (id, payload)  => api.post(`/records/${id}/review/`, payload),
  bulkReview: (payload)  => api.post("/records/bulk-review/", payload),
};

export const auditApi = {
  list: (params) => api.get("/audit-log/", { params }),
};
