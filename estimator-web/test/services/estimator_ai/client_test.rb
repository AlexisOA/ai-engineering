require "test_helper"
require "webmock/minitest"

module EstimatorAi
  class ClientTest < ActiveSupport::TestCase
    setup do
      WebMock.disable_net_connect!
      @request = EstimationRequest.new(
        description: "Mobile app with login, chat and push notifications",
        project_type: "mobile_app",
        detail_level: "medium",
        output_format: "phases_table"
      )
      @client = EstimatorAi::Client.new(base_url: "http://ai-test")
    end

    teardown do
      WebMock.reset!
      WebMock.allow_net_connect!
    end

    def structured_body
      {
        result: {
          summary: "Mid-size mobile app build.",
          confidence_pct: 70,
          phases: [
            { name: "Discovery", duration_weeks: 1, cost_eur: 5_000, summary: "Scoping." },
            { name: "Build", duration_weeks: 6, cost_eur: 20_000, summary: "Core features." }
          ],
          total_duration_weeks: 7,
          total_cost_eur: 25_000
        },
        prompt_version: "v1",
        cached: false
      }
    end

    test "returns raw Hash payload on 200 with structured body" do
      stub_request(:post, "http://ai-test/api/v1/estimate")
        .with(body: @request.to_payload.to_json)
        .to_return(
          status: 200,
          body: structured_body.to_json,
          headers: { "Content-Type" => "application/json" }
        )

      payload = @client.estimate(@request)

      assert_kind_of Hash, payload
      assert_equal "v1", payload["prompt_version"]
      assert_equal false, payload["cached"]
      assert_equal 25_000, payload.dig("result", "total_cost_eur")
      assert_equal 2, payload.dig("result", "phases").size
    end

    test "cached flag is propagated from the API" do
      stub_request(:post, "http://ai-test/api/v1/estimate")
        .to_return(
          status: 200,
          body: structured_body.merge(cached: true).to_json,
          headers: { "Content-Type" => "application/json" }
        )

      payload = @client.estimate(@request)
      assert_equal true, payload["cached"]
    end

    test "raises GuardrailViolation on 400 with prompt_injection reason" do
      stub_request(:post, "http://ai-test/api/v1/estimate")
        .to_return(
          status: 400,
          body: {
            detail: { reason: "prompt_injection", message: "suspicious 'ignore previous instructions'" }
          }.to_json,
          headers: { "Content-Type" => "application/json" }
        )

      err = assert_raises(EstimatorAi::Client::GuardrailViolation) do
        @client.estimate(@request)
      end
      assert_includes err.message, "prompt_injection"
    end

    test "raises GuardrailViolation on 400 with moderation reason" do
      stub_request(:post, "http://ai-test/api/v1/estimate")
        .to_return(
          status: 400,
          body: { detail: { reason: "moderation", message: "flagged: hate" } }.to_json,
          headers: { "Content-Type" => "application/json" }
        )

      err = assert_raises(EstimatorAi::Client::GuardrailViolation) { @client.estimate(@request) }
      assert_includes err.message, "moderation"
    end

    test "raises GuardrailViolation on 400 with pii reason" do
      stub_request(:post, "http://ai-test/api/v1/estimate")
        .to_return(
          status: 400,
          body: { detail: { reason: "pii", message: "email detected" } }.to_json,
          headers: { "Content-Type" => "application/json" }
        )

      err = assert_raises(EstimatorAi::Client::GuardrailViolation) { @client.estimate(@request) }
      assert_includes err.message, "pii"
    end

    test "falls back to InvalidRequest on 400 with unknown reason" do
      stub_request(:post, "http://ai-test/api/v1/estimate")
        .to_return(
          status: 400,
          body: { detail: "something else went wrong" }.to_json,
          headers: { "Content-Type" => "application/json" }
        )

      assert_raises(EstimatorAi::Client::InvalidRequest) { @client.estimate(@request) }
    end

    test "raises InvalidRequest on 422" do
      stub_request(:post, "http://ai-test/api/v1/estimate")
        .to_return(
          status: 422,
          body: { detail: "description too short" }.to_json,
          headers: { "Content-Type" => "application/json" }
        )

      err = assert_raises(EstimatorAi::Client::InvalidRequest) { @client.estimate(@request) }
      assert_includes err.message, "description too short"
    end

    test "raises ServerError on 502 with upstream LLM message" do
      stub_request(:post, "http://ai-test/api/v1/estimate")
        .to_return(status: 502, body: { detail: "Upstream LLM call failed" }.to_json,
                   headers: { "Content-Type" => "application/json" })

      err = assert_raises(EstimatorAi::Client::ServerError) { @client.estimate(@request) }
      assert_includes err.message, "Upstream LLM call failed"
    end

    test "raises ServerError on unexpected status" do
      stub_request(:post, "http://ai-test/api/v1/estimate")
        .to_return(status: 500, body: "")

      assert_raises(EstimatorAi::Client::ServerError) { @client.estimate(@request) }
    end

    test "raises ArgumentError when request is invalid" do
      bad = EstimationRequest.new
      assert_raises(ArgumentError) { @client.estimate(bad) }
    end

    # --- Session 5: conversational endpoints ---------------------------------

    test "create_session POSTs /sessions and returns the body" do
      stub_request(:post, "http://ai-test/sessions")
        .to_return(status: 201, body: { session_id: "abc-123" }.to_json,
                   headers: { "Content-Type" => "application/json" })

      body = @client.create_session
      assert_equal "abc-123", body["session_id"]
    end

    test "create_session raises ServerError when status is not 201" do
      stub_request(:post, "http://ai-test/sessions").to_return(status: 500, body: "")
      assert_raises(EstimatorAi::Client::ServerError) { @client.create_session }
    end

    test "get_session returns body and raises SessionNotFound on 404" do
      stub_request(:get, "http://ai-test/sessions/abc")
        .to_return(status: 200,
                   body: { session_id: "abc", message_count: 4, metadata: { project_name: "X" } }.to_json,
                   headers: { "Content-Type" => "application/json" })
      body = @client.get_session("abc")
      assert_equal 4, body["message_count"]

      stub_request(:get, "http://ai-test/sessions/missing").to_return(status: 404, body: "{}")
      assert_raises(EstimatorAi::Client::SessionNotFound) { @client.get_session("missing") }
    end

    test "estimate_in_session without attachments POSTs urlencoded form" do
      stub_request(:post, "http://ai-test/sessions/abc/estimate")
        .with do |req|
          req.headers["Content-Type"].to_s.include?("application/x-www-form-urlencoded") &&
            req.body.to_s.include?("project_type=web_saas")
        end
        .to_return(
          status: 200,
          body: structured_body.merge(prompt_version: "v2").to_json,
          headers: { "Content-Type" => "application/json" }
        )

      req = SessionEstimationRequest.new(
        transcript:   "Conversational transcript long enough to clear validation.",
        project_type: "web_saas",
        detail_level: "medium",
        output_format: "phases_table"
      )

      payload = @client.estimate_in_session("abc", req)
      assert_equal "v2", payload["prompt_version"]
    end

    test "estimate_in_session with attachments POSTs multipart/form-data" do
      stub_request(:post, "http://ai-test/sessions/abc/estimate")
        .with do |req|
          req.headers["Content-Type"].to_s.start_with?("multipart/form-data") &&
            req.body.to_s.include?("spec.pdf") &&
            req.body.to_s.include?("Conversational transcript")
        end
        .to_return(
          status: 200,
          body: structured_body.merge(prompt_version: "v2").to_json,
          headers: { "Content-Type" => "application/json" }
        )

      req = SessionEstimationRequest.new(
        transcript:   "Conversational transcript long enough to clear validation.",
        project_type: "web_saas",
        detail_level: "medium",
        output_format: "phases_table"
      )

      tempfile = Tempfile.new([ "spec", ".pdf" ])
      tempfile.write("%PDF-fake-bytes")
      tempfile.rewind
      upload = ActionDispatch::Http::UploadedFile.new(
        tempfile: tempfile, filename: "spec.pdf", type: "application/pdf"
      )

      payload = @client.estimate_in_session("abc", req, attachments: [ upload ])
      assert_equal "v2", payload["prompt_version"]
    ensure
      tempfile&.close
      tempfile&.unlink
    end

    test "estimate_in_session raises SessionNotFound on 404" do
      stub_request(:post, "http://ai-test/sessions/abc/estimate")
        .to_return(status: 404, body: { detail: "session_not_found" }.to_json,
                   headers: { "Content-Type" => "application/json" })

      req = SessionEstimationRequest.new(
        transcript:   "Conversational transcript long enough to clear validation.",
        project_type: "web_saas",
        detail_level: "medium",
        output_format: "phases_table"
      )
      assert_raises(EstimatorAi::Client::SessionNotFound) { @client.estimate_in_session("abc", req) }
    end

    test "estimate_in_session_acb hits the ACB endpoint and returns the acb trace" do
      stub_request(:post, "http://ai-test/sessions/abc/estimate-acb")
        .with do |req|
          req.headers["Content-Type"].to_s.include?("application/x-www-form-urlencoded") &&
            req.body.to_s.include?("project_type=web_saas") &&
            req.body.to_s.include?("tier=executive")
        end
        .to_return(
          status: 200,
          body: structured_body.merge(
            prompt_version: "v3",
            acb: { iterations: [], final_decision: "accept", iterations_run: 1 }
          ).to_json,
          headers: { "Content-Type" => "application/json" }
        )

      req = SessionEstimationRequest.new(
        transcript:   "Conversational transcript long enough to clear validation.",
        project_type: "web_saas",
        detail_level: "medium",
        output_format: "phases_table"
      )

      payload = @client.estimate_in_session_acb("abc", req, tier: "executive")
      assert_equal "accept", payload.dig("acb", "final_decision")
      assert_equal "v3", payload["prompt_version"]
    end

    test "estimate_in_session ignores tier when set to auto" do
      stub_request(:post, "http://ai-test/sessions/abc/estimate")
        .with do |req|
          # 'tier=' must NOT appear because Auto means: let FastAPI derive it.
          !req.body.to_s.include?("tier=")
        end
        .to_return(status: 200, body: structured_body.to_json,
                   headers: { "Content-Type" => "application/json" })

      req = SessionEstimationRequest.new(
        transcript:   "Conversational transcript long enough to clear validation.",
        project_type: "web_saas",
        detail_level: "medium",
        output_format: "phases_table"
      )
      payload = @client.estimate_in_session("abc", req, tier: "auto")
      assert_equal "v1", payload["prompt_version"]
    end

    test "estimate_in_session surfaces guardrail violations like the transactional path" do
      stub_request(:post, "http://ai-test/sessions/abc/estimate")
        .to_return(status: 400,
                   body: { detail: { reason: "pii", message: "email detected" } }.to_json,
                   headers: { "Content-Type" => "application/json" })

      req = SessionEstimationRequest.new(
        transcript:   "Conversational transcript long enough to clear validation.",
        project_type: "web_saas",
        detail_level: "medium",
        output_format: "phases_table"
      )
      err = assert_raises(EstimatorAi::Client::GuardrailViolation) do
        @client.estimate_in_session("abc", req)
      end
      assert_includes err.message, "pii"
    end
  end
end
