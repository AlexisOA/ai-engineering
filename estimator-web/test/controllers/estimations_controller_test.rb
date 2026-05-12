require "test_helper"
require "webmock/minitest"

class EstimationsControllerTest < ActionDispatch::IntegrationTest
  setup do
    WebMock.disable_net_connect!
    @base_url = Rails.application.config.estimator_ai.base_url
    @valid_params = {
      estimation_request: {
        description: "Mobile app with login, chat and push notifications, multi-tenant",
        project_type: "mobile_app",
        detail_level: "medium",
        output_format: "phases_table"
      }
    }
  end

  teardown do
    WebMock.reset!
    WebMock.allow_net_connect!
  end

  test "GET new returns 200 with empty form" do
    get new_estimation_path
    assert_response :success
    assert_select "form"
    assert_select "textarea[name='estimation_request[description]']"
  end

  test "POST create with valid params calls client and renders show" do
    stub_request(:post, "#{@base_url}/api/v1/estimate")
      .to_return(
        status: 200,
        body: { text: "12-week estimation across 3 phases", prompt_version: "v1" }.to_json,
        headers: { "Content-Type" => "application/json" }
      )

    post estimation_path, params: @valid_params
    assert_response :success
    assert_select "h1", "Estimation"
    assert_match "12-week estimation", response.body
    assert_match "v1", response.body
  end

  test "POST create with invalid params re-renders new with 422" do
    bad = @valid_params.deep_dup
    bad[:estimation_request][:description] = "too short"

    post estimation_path, params: bad
    assert_response :unprocessable_entity
    assert_select "form"
  end

  test "POST create handles InvalidRequest from upstream" do
    stub_request(:post, "#{@base_url}/api/v1/estimate")
      .to_return(status: 422, body: { detail: "prompt injection detected" }.to_json,
                 headers: { "Content-Type" => "application/json" })

    post estimation_path, params: @valid_params
    assert_response :unprocessable_entity
    assert_match "prompt injection detected", response.body
  end

  test "POST create handles ServerError from upstream" do
    stub_request(:post, "#{@base_url}/api/v1/estimate")
      .to_return(status: 502, body: { detail: "boom" }.to_json,
                 headers: { "Content-Type" => "application/json" })

    post estimation_path, params: @valid_params
    assert_response :service_unavailable
    assert_match "AI service unavailable", response.body
  end

  test "POST create handles connection failure" do
    stub_request(:post, "#{@base_url}/api/v1/estimate").to_timeout

    post estimation_path, params: @valid_params
    assert_response :service_unavailable
    assert_match "AI service unavailable", response.body
  end
end
