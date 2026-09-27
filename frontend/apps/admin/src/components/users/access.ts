/** Kirish ma'lumotlari (POST /users/{id}/password javobi) */
export type Access = { user_id: string; full_name: string; phone: string; password: string; login_url: string; telegram_linked: boolean; telegram_sent: boolean; restaurant: string }
