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

    test "returns EstimationResponse on 200" do
      stub_request(:post, "http://ai-test/api/v1/estimate")
        .with(body: @request.to_payload.to_json)
        .to_return(
          status: 200,
          body: { text: "Estimated 12 weeks", prompt_version: "v1" }.to_json,
          headers: { "Content-Type" => "application/json" }
        )

      response = @client.estimate(@request)

      assert_kind_of EstimationResponse, response
      assert_equal "Estimated 12 weeks", response.text
      assert_equal "v1", response.prompt_version
    end

    test "raises InvalidRequest on 422" do
      stub_request(:post, "http://ai-test/api/v1/estimate")
        .to_return(
          status: 422,
          body: { detail: "prompt injection detected" }.to_json,
          headers: { "Content-Type" => "application/json" }
        )

      err = assert_raises(EstimatorAi::Client::InvalidRequest) do
        @client.estimate(@request)
      end
      assert_includes err.message, "prompt injection detected"
    end

    test "raises ServerError on 502 with upstream LLM message" do
      stub_request(:post, "http://ai-test/api/v1/estimate")
        .to_return(status: 502, body: { detail: "Upstream LLM call failed" }.to_json,
                   headers: { "Content-Type" => "application/json" })

      err = assert_raises(EstimatorAi::Client::ServerError) do
        @client.estimate(@request)
      end
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
  end
end
