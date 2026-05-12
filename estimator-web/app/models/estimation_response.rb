class EstimationResponse
  include ActiveModel::Model
  include ActiveModel::Attributes

  attribute :text,           :string
  attribute :prompt_version, :string

  def self.from_hash(hash)
    new(
      text: hash["text"],
      prompt_version: hash["prompt_version"]
    )
  end
end
