import { render, screen } from '@testing-library/react'
import { ApiError } from '../api/client'
import { ErrorBox } from './ui'

describe('ErrorBox', () => {
  it('shows the trace ID as a reference for server errors', () => {
    render(<ErrorBox error={new ApiError(500, 'Internal server error', {}, '4bf92f3577b34da6a3ce929d0e0e4736')} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Reference: 4bf92f3577b34da6a3ce929d0e0e4736')
  })

  it("doesn't for the customer's own mistakes (4xx), where it would only be noise", () => {
    render(<ErrorBox error={new ApiError(409, 'Another delivery partner has taken this order', {}, '4bf92f3577b34da6a3ce929d0e0e4736')} />)
    expect(screen.queryByText(/Reference/)).not.toBeInTheDocument()
  })
})
