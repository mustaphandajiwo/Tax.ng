// Typed client for the academy module (backend/taxng/modules/academy/routes.py).
import type { ParameterCard, ReviewStatus } from "../../api";
import { http } from "../../http";

export interface Trainer {
  id: string;
  name: string;
  headline: string;
  bio: string[];
  sample: boolean;
}

export interface Cpd {
  accredited: true;
  body: "CITN" | "ICAN";
  reference: string;
  approved_at: string;
}

export interface Price {
  model: "free" | "paid";
  label: string;
  placeholder?: boolean;
  note?: string;
}

export interface CourseSummary {
  id: string;
  title: string;
  summary: string;
  level: string;
  audience: string[];
  duration_hours: number | null;
  review_status: ReviewStatus;
  price: Price;
  cpd: Cpd | null;
  trainer: Trainer;
  lesson_count: number;
}

export interface Checkout {
  checkout_id: string | null;
  url: string | null;
  mode: string | null;
}

export interface Enrolment {
  id: string;
  course_id: string;
  cohort_id: string | null;
  status: "pending_payment" | "active" | "cancelled";
  source: "free" | "paid" | "seat";
  created_at: string;
  activated_at: string | null;
  checkout?: Checkout;
}

export interface MyEnrolment extends Enrolment {
  course_title: string;
  lessons_done: number;
  lesson_count: number;
  certified: boolean;
}

export interface Outline extends CourseSummary {
  review_note: string;
  payments_available: boolean;
  cohorts: { id: string; label: string; starts_on: string | null; capacity: number | null; places_left: number | null }[];
  modules: { id: string; title: string; lessons: { id: string; title: string }[]; has_quiz: boolean }[];
  assessment: { question_count: number; pass_mark_percent: number };
  case_study: { title: string } | null;
  my_enrolment: Enrolment | null;
}

export interface QuizQuestion {
  id: string;
  prompt: string;
  options: { id: string; text: string }[];
}

export interface Quiz {
  id: string;
  kind: "quiz" | "assessment";
  pass_mark_percent: number;
  questions: QuizQuestion[];
}

export interface Lesson {
  id: string;
  title: string;
  body: string[];
  figures: ParameterCard[];
  provisions: { id: string; title: string }[];
  completed: boolean;
}

export interface Certificate {
  code: string;
  holder_name: string;
  issued_at: string;
  cpd: Cpd | null;
}

export interface CaseStudy {
  title: string;
  calculator?: string;
  scenario: string[];
  tasks: string[];
  discussion: string[];
}

export interface Player {
  enrolment: Enrolment;
  course: CourseSummary;
  review_note: string;
  modules: { id: string; title: string; lessons: Lesson[]; quiz: Quiz | null }[];
  assessment: Quiz;
  case_study: CaseStudy | null;
  results: Record<string, { attempts: number; best_correct: number; total: number; passed: boolean }>;
  certificate: Certificate | null;
}

export interface GradeResult {
  attempt_id: string;
  quiz_id: string;
  kind: "quiz" | "assessment";
  correct: number;
  total: number;
  pass_mark_percent: number;
  passed: boolean;
  results: { id: string; chosen: string | null; correct: boolean; answer: string; explanation: string }[];
}

export interface Verification {
  valid: true;
  code: string;
  holder_name: string;
  course_id: string;
  course_title: string;
  issued_at: string;
  issuer: string;
  cpd: Cpd | null;
}

export interface SeatPool {
  id: string;
  course_id: string;
  course_title: string;
  seats_total: number;
  seats_used: number;
  status: "pending_payment" | "active";
  checkout: Checkout | null;
  assigned: { user_id: string; email: string; name: string; assigned_at: string }[];
}

export interface OrgMember {
  id: string;
  email: string;
  name: string;
  role: string;
}

const enc = encodeURIComponent;

export const academyApi = {
  courses: () => http.get<{ items: CourseSummary[]; payments_available: boolean }>("/api/academy/courses"),
  course: (id: string) => http.get<Outline>(`/api/academy/courses/${enc(id)}`),
  enrol: (id: string, cohortId?: string) => http.post<Enrolment>(`/api/academy/courses/${enc(id)}/enrol`, cohortId ? { cohort_id: cohortId } : {}),
  mine: () => http.get<{ items: MyEnrolment[] }>("/api/academy/me/enrolments"),
  player: (enrolmentId: string) => http.get<Player>(`/api/academy/enrolments/${enc(enrolmentId)}`),
  complete: (enrolmentId: string, lessonId: string) =>
    http.post<{ lessons_done: number; lesson_count: number }>(`/api/academy/enrolments/${enc(enrolmentId)}/lessons/${enc(lessonId)}/complete`),
  attempt: (enrolmentId: string, quizId: string, answers: Record<string, string>) =>
    http.post<GradeResult>(`/api/academy/enrolments/${enc(enrolmentId)}/quizzes/${enc(quizId)}/attempts`, { answers }),
  certificate: (enrolmentId: string, name: string) => http.post<Certificate>(`/api/academy/enrolments/${enc(enrolmentId)}/certificate`, { name }),
  verify: (code: string) => http.get<Verification>(`/api/academy/certificates/${enc(code)}`),
  seats: (orgId: string) => http.get<{ items: SeatPool[]; members: OrgMember[] }>(`/api/academy/orgs/${enc(orgId)}/seats`),
  buySeats: (orgId: string, courseId: string, seats: number) => http.post<SeatPool>(`/api/academy/orgs/${enc(orgId)}/seats`, { course_id: courseId, seats }),
  assignSeat: (orgId: string, poolId: string, userId: string) =>
    http.post<{ enrolment_id: string }>(`/api/academy/orgs/${enc(orgId)}/seats/${enc(poolId)}/assign`, { user_id: userId }),
  approveCpd: (courseId: string, body: string, reference: string) => http.post<Cpd>(`/api/academy/courses/${enc(courseId)}/cpd`, { body, reference }),
  withdrawCpd: (courseId: string) => http.post<{ status: string }>(`/api/academy/courses/${enc(courseId)}/cpd/withdraw`),
};
