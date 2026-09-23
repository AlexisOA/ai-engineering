# Context client for the transactional estimation flow (Session 4).
# One endpoint: free-text in, validated structured estimation out.
#
# Session 15: the estimator is unreachable from the host in the containerized
# deploy, but any other service on the compose network could still call it, so
# every request carries a shared X-Service-Token (injected once via
# BaseClient#default_headers, same pattern RagEstimateClient uses for X-API-Key).
module EstimatorAi
  class EstimationsClient < BaseClient
    def initialize(base_url: Rails.application.config.estimator_ai.base_url,
                    timeout: Rails.application.config.estimator_ai.timeout)
      super(
        base_url: base_url,
        timeout: timeout,
        default_headers: { "X-Service-Token" => Rails.application.config.estimator_ai.ai_service_token }
      )
    end

    # ``request`` is an Estimation::Request (the Pydantic EstimationRequest mirror).
    def estimate(request)
      raise ArgumentError, "request must be valid" unless request.valid?

      response = json_conn.post("/api/v1/estimate", request.to_payload)
      handle_response(response)
    end
  end
end
