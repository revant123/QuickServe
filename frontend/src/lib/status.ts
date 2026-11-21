import type { OrderStatus } from '../api/types'

export const STATUS_LABEL: Record<OrderStatus, string> = {
  PLACED: 'Waiting for payment',
  PAID: 'Waiting for the restaurant',
  ACCEPTED: 'Accepted',
  PREPARING: 'Being cooked',
  READY: 'Packed',
  OUT_FOR_DELIVERY: 'On the way',
  DELIVERED: 'Delivered',
  CANCELLED: 'Cancelled',
  REJECTED: 'Rejected',
  PAYMENT_FAILED: 'Not paid',
}
