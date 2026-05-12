class EstimationsController < ApplicationController
  def new
    @request = EstimationRequest.new
  end

  def create
    @request = EstimationRequest.new(estimation_request_params)

    unless @request.valid?
      render :new, status: :unprocessable_entity
      return
    end

    @response = EstimatorAi::Client.new.estimate(@request)
    render :show
  rescue EstimatorAi::Client::InvalidRequest => e
    flash.now[:alert] = e.message
    render :new, status: :unprocessable_entity
  rescue EstimatorAi::Client::ServerError, Faraday::ConnectionFailed, Faraday::TimeoutError => e
    flash.now[:alert] = "AI service unavailable: #{e.message}"
    render :new, status: :service_unavailable
  end

  private

  def estimation_request_params
    params.require(:estimation_request).permit(
      :description, :project_type, :detail_level, :output_format
    )
  end
end
