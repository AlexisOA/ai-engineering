require "faraday"
require "faraday/multipart"

module EstimatorAi
  class Client
    Error              = Class.new(StandardError)
    InvalidRequest     = Class.new(Error)
    GuardrailViolation = Class.new(Error)
    SessionNotFound    = Class.new(Error)
    ServerError        = Class.new(Error)

    GUARDRAIL_REASONS = %w[moderation prompt_injection pii].freeze

    def initialize(base_url: Rails.application.config.estimator_ai.base_url,
                   timeout:  Rails.application.config.estimator_ai.timeout)
      @base_url = base_url
      @timeout  = timeout
    end

    # --- Session 4 transactional path (unchanged) -------------------------------------

    def estimate(request)
      raise ArgumentError, "request must be valid" unless request.valid?

      response = json_conn.post("/api/v1/estimate", request.to_payload)
      handle_response(response)
    end

    # --- Session 5 conversational path ------------------------------------------------

    def create_session
      response = json_conn.post("/sessions")
      raise ServerError, "unexpected status #{response.status}" unless response.status == 201
      response.body
    end

    def get_session(session_id)
      response = json_conn.get("/sessions/#{session_id}")
      case response.status
      when 200 then response.body
      when 404 then raise SessionNotFound, session_id
      else
        raise ServerError, "unexpected status #{response.status}"
      end
    end

    # ``request`` is a SessionEstimationRequest; ``attachments`` is an array of
    # ActionDispatch::Http::UploadedFile (or anything responding to
    # tempfile/original_filename/content_type).
    def estimate_in_session(session_id, request, attachments: [])
      raise ArgumentError, "request must be valid" unless request.valid?

      body = {
        "transcript"    => request.transcript,
        "project_type"  => request.project_type,
        "detail_level"  => request.detail_level,
        "output_format" => request.output_format
      }
      attachments.compact.each do |file|
        body["attachments"] = [] unless body["attachments"].is_a?(Array)
        body["attachments"] << Faraday::Multipart::FilePart.new(
          file.tempfile,
          file.content_type || "application/octet-stream",
          file.original_filename
        )
      end

      response = multipart_conn.post("/sessions/#{session_id}/estimate", body)
      handle_response(response)
    end

    private

    def json_conn
      @json_conn ||= Faraday.new(url: @base_url) do |f|
        f.request  :json
        f.response :json
        f.options.timeout = @timeout
        f.adapter Faraday.default_adapter
      end
    end

    def multipart_conn
      @multipart_conn ||= Faraday.new(url: @base_url) do |f|
        f.request  :multipart
        f.request  :url_encoded
        f.response :json
        f.options.timeout = @timeout
        f.adapter Faraday.default_adapter
      end
    end

    def handle_response(response)
      case response.status
      when 200
        response.body
      when 400
        detail = extract_detail(response.body)
        reason = detail.is_a?(Hash) ? detail["reason"] : nil
        if GUARDRAIL_REASONS.include?(reason)
          message = detail.is_a?(Hash) ? detail["message"] || reason : reason
          raise GuardrailViolation, "Input rejected (#{reason}): #{message}"
        else
          raise InvalidRequest, detail.to_s
        end
      when 404
        raise SessionNotFound, extract_detail(response.body).to_s
      when 415, 422
        raise InvalidRequest, extract_detail(response.body).to_s
      when 502
        raise ServerError, "Upstream LLM call failed"
      else
        raise ServerError, "unexpected status #{response.status}"
      end
    end

    def extract_detail(body)
      return body unless body.is_a?(Hash)
      body["detail"] || body
    end
  end
end
