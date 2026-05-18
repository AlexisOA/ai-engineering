# Form-backed model for the conversational /sessions/:id/estimate endpoint.
# Mirrors EstimationRequest but renames description -> transcript to match the
# FastAPI multipart contract.
class SessionEstimationRequest
  include ActiveModel::Model
  include ActiveModel::Attributes

  PROJECT_TYPES  = EstimationRequest::PROJECT_TYPES
  DETAIL_LEVELS  = EstimationRequest::DETAIL_LEVELS
  OUTPUT_FORMATS = EstimationRequest::OUTPUT_FORMATS

  attribute :transcript,    :string
  attribute :project_type,  :string
  attribute :detail_level,  :string, default: "medium"
  attribute :output_format, :string, default: "phases_table"

  validates :transcript,    presence: true, length: { in: 20..80000 }
  validates :project_type,  presence: true, inclusion: { in: PROJECT_TYPES }
  validates :detail_level,  inclusion: { in: DETAIL_LEVELS }
  validates :output_format, inclusion: { in: OUTPUT_FORMATS }
end
